from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, cast

from .config import EventStreamConfig
from .errors import ConflictError, ValidationError
from .utils import now


@dataclass(frozen=True)
class EventPointer:
    run_id: str
    seq: int


class SqliteEventStore:
    def __init__(self, config: EventStreamConfig) -> None:
        self._db_path = config.db_path
        self._retention_days = config.retention_days
        self._ensure_db_dir()
        self._init_db()

    def append_events(self, events: list[dict[str, object]]) -> tuple[list[EventPointer], dict[str, int]]:
        if not events:
            raise ValidationError("No events provided.")

        run_ids: list[str] = []
        for event in events:
            run_id_raw = event.get("run_id")
            if not isinstance(run_id_raw, str) or not run_id_raw:
                raise ValidationError("Event missing run_id.")
            run_ids.append(run_id_raw)

        pointers: list[EventPointer] = []
        next_seq_by_run: dict[str, int] = {}

        with self._connect() as conn:
            max_seq_by_run = _fetch_max_seq(conn, run_ids)
            next_seq_by_run = {run_id: max_seq_by_run.get(run_id, 0) + 1 for run_id in set(run_ids)}

            for event in events:
                run_id = cast(str, event["run_id"])
                if (seq := event.get("seq")) is None:
                    seq = next_seq_by_run[run_id]
                    next_seq_by_run[run_id] = seq + 1
                    event["seq"] = seq
                if not isinstance(seq, int):
                    raise ValidationError("Event seq must be an int.")
                next_seq_by_run[run_id] = max(next_seq_by_run[run_id], seq + 1)
                node_run_id = event.get("node_run_id")
                event_time = event.get("time")
                if not isinstance(event_time, str) or not event_time:
                    event_time = now()
                    event["time"] = event_time

                event_json = json.dumps(event, separators=(",", ":"), ensure_ascii=True)
                try:
                    conn.execute(
                        "INSERT INTO run_events (run_id, seq, node_run_id, time, event_json) VALUES (?, ?, ?, ?, ?)",
                        (run_id, seq, node_run_id, event_time, event_json),
                    )
                except sqlite3.IntegrityError as exc:
                    raise ConflictError("Event already exists for run_id/seq.") from exc

                pointers.append(EventPointer(run_id=run_id, seq=seq))

            if self._retention_days:
                _apply_retention(conn, self._retention_days)

        return pointers, next_seq_by_run

    def list_events(
        self,
        *,
        run_id: str | None = None,
        node_run_id: str | None = None,
        after_seq: int = 0,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        if run_id is None and node_run_id is None:
            raise ValidationError("run_id or node_run_id is required.")
        with self._connect() as conn:
            if run_id is not None:
                rows = conn.execute(
                    "SELECT event_json FROM run_events WHERE run_id = ? AND seq > ? ORDER BY seq LIMIT ?",
                    (run_id, after_seq, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT event_json FROM run_events WHERE node_run_id = ? AND seq > ? ORDER BY seq LIMIT ?",
                    (node_run_id, after_seq, limit),
                ).fetchall()
        return [json.loads(row["event_json"]) for row in rows]

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _ensure_db_dir(self) -> None:
        if self._db_path.parent:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS run_events ("
                "run_id TEXT NOT NULL, "
                "seq INTEGER NOT NULL, "
                "node_run_id TEXT, "
                "time TEXT NOT NULL, "
                "event_json TEXT NOT NULL, "
                "PRIMARY KEY (run_id, seq)"
                ")"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_run_events_run_id ON run_events(run_id, seq)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_run_events_node_run_id ON run_events(node_run_id, seq)"
            )


def _fetch_max_seq(conn: sqlite3.Connection, run_ids: Iterable[str]) -> dict[str, int]:
    max_seq_by_run: dict[str, int] = {}
    for run_id in set(run_ids):
        row = conn.execute("SELECT MAX(seq) AS max_seq FROM run_events WHERE run_id = ?", (run_id,)).fetchone()
        max_seq_by_run[run_id] = row["max_seq"] or 0
    return max_seq_by_run


def _apply_retention(conn: sqlite3.Connection, retention_days: int) -> None:
    cutoff_seconds = retention_days * 24 * 60 * 60
    cutoff = _iso_from_epoch_seconds(_epoch_seconds() - cutoff_seconds)
    conn.execute("DELETE FROM run_events WHERE time < ?", (cutoff,))


def _epoch_seconds() -> int:
    import time

    return int(time.time())


def _iso_from_epoch_seconds(epoch_seconds: int) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).isoformat()
