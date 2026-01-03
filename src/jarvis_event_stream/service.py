from __future__ import annotations

import asyncio
import json
import logging
from typing import Annotated, Any, AsyncIterator
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from arp_standard_model import Health, Status, VersionInfo
from arp_standard_server import AuthSettings
from arp_standard_server.auth import register_auth_middleware

from . import __version__
from .config import EventStreamConfig, event_stream_config_from_env
from .errors import ConflictError, ValidationError
from .sqlite import EventPointer, SqliteEventStore
from .utils import auth_settings_from_env_or_dev_secure, decode_cursor, encode_cursor, now

logger = logging.getLogger(__name__)


class AppendEventsRequest(BaseModel):
    events: list[dict[str, Any]] = Field(default_factory=list)


class EventPointerResponse(BaseModel):
    run_id: str
    seq: int


class AppendEventsResponse(BaseModel):
    items: list[EventPointerResponse]
    next_seq_by_run: dict[str, int]


def create_app(
    config: EventStreamConfig | None = None,
    auth_settings: AuthSettings | None = None,
) -> FastAPI:
    cfg = config or event_stream_config_from_env()
    store = SqliteEventStore(cfg)
    logger.info("Event Stream config (db_path=%s, retention_days=%s)", cfg.db_path, cfg.retention_days)

    app = FastAPI(title="JARVIS Event Stream", version=__version__)
    auth_settings = auth_settings or auth_settings_from_env_or_dev_secure()
    logger.info(
        "Event Stream auth settings (mode=%s, issuer=%s)",
        getattr(auth_settings, "mode", None),
        getattr(auth_settings, "issuer", None),
    )
    register_auth_middleware(app, settings=auth_settings)

    @app.get("/v1/health", response_model=Health)
    async def health() -> Health:
        return Health(status=Status.ok, time=datetime.now(timezone.utc))

    @app.get("/v1/version", response_model=VersionInfo)
    async def version() -> VersionInfo:
        return VersionInfo(
            service_name="arp-jarvis-eventstream",
            service_version=__version__,
            supported_api_versions=["v1"],
        )

    @app.post("/v1/run-events", response_model=AppendEventsResponse)
    async def append_events(request: AppendEventsRequest) -> AppendEventsResponse:
        run_ids = {
            event.get("run_id")
            for event in request.events
            if isinstance(event, dict) and event.get("run_id")
        }
        logger.info(
            "Event append requested (events=%s, runs=%s)",
            len(request.events),
            len(run_ids),
        )
        try:
            pointers, next_seq_by_run = store.append_events(request.events)
        except ValidationError as exc:
            logger.warning("Event append validation failed")
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ConflictError as exc:
            logger.warning("Event append conflict")
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        logger.info(
            "Event append completed (events=%s, runs=%s)",
            len(pointers),
            len(next_seq_by_run),
        )
        return AppendEventsResponse(
            items=[EventPointerResponse(run_id=pointer.run_id, seq=pointer.seq) for pointer in pointers],
            next_seq_by_run=next_seq_by_run,
        )

    @app.get("/v1/runs/{run_id}/events")
    async def stream_run_events(
        run_id: str,
        cursor: str | None = None,
        follow: Annotated[int, Query(ge=0, le=1)] = 0,
        limit: Annotated[int | None, Query(ge=1, le=10000)] = None,
    ) -> StreamingResponse:
        logger.info(
            "Run event stream requested (run_id=%s, cursor=%s, follow=%s, limit=%s)",
            run_id,
            cursor,
            bool(follow),
            limit,
        )
        try:
            start_seq = decode_cursor(cursor) if cursor else 0
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        generator = _event_stream(
            store,
            run_id=run_id,
            start_seq=start_seq,
            follow=bool(follow),
            limit=limit,
            node_run_id=None,
        )
        return StreamingResponse(generator, media_type="application/x-ndjson")

    @app.get("/v1/node-runs/{node_run_id}/events")
    async def stream_node_run_events(
        node_run_id: str,
        cursor: str | None = None,
        follow: Annotated[int, Query(ge=0, le=1)] = 0,
        limit: Annotated[int | None, Query(ge=1, le=10000)] = None,
    ) -> StreamingResponse:
        logger.info(
            "NodeRun event stream requested (node_run_id=%s, cursor=%s, follow=%s, limit=%s)",
            node_run_id,
            cursor,
            bool(follow),
            limit,
        )
        try:
            start_seq = decode_cursor(cursor) if cursor else 0
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        generator = _event_stream(
            store,
            run_id=None,
            start_seq=start_seq,
            follow=bool(follow),
            limit=limit,
            node_run_id=node_run_id,
        )
        return StreamingResponse(generator, media_type="application/x-ndjson")

    return app


async def _event_stream(
    store: SqliteEventStore,
    *,
    run_id: str | None,
    node_run_id: str | None,
    start_seq: int,
    follow: bool,
    limit: int | None,
) -> AsyncIterator[str]:
    sent = 0
    cursor_seq = start_seq
    batch_size = 200

    while True:
        remaining = None if limit is None else max(limit - sent, 0)
        if remaining == 0:
            return
        fetch_limit = batch_size if remaining is None else min(batch_size, remaining)

        events = await asyncio.to_thread(
            store.list_events,
            run_id=run_id,
            node_run_id=node_run_id,
            after_seq=cursor_seq,
            limit=fetch_limit,
        )
        if not events:
            if not follow:
                return
            await asyncio.sleep(0.25)
            continue

        for event in events:
            seq = event.get("seq")
            if isinstance(seq, int):
                cursor_seq = seq
            yield json.dumps(event, separators=(",", ":"), ensure_ascii=True) + "\n"
            sent += 1
            if limit is not None and sent >= limit:
                return
