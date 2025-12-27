from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EventStreamConfig:
    db_url: str
    retention_days: int | None

    @property
    def db_path(self) -> Path:
        return Path(_sqlite_path(self.db_url))


def event_stream_config_from_env() -> EventStreamConfig:
    db_url = os.getenv("JARVIS_EVENT_STORE_DB_URL", "sqlite:///./runs/jarvis_event_store.sqlite")
    retention_raw = os.getenv("JARVIS_EVENT_RETENTION_DAYS")
    retention_days = int(retention_raw) if retention_raw else None
    return EventStreamConfig(db_url=db_url, retention_days=retention_days)


def _sqlite_path(db_url: str) -> str:
    prefix = "sqlite:///"
    if not db_url.startswith(prefix):
        raise ValueError("Only sqlite:/// URLs are supported for JARVIS Event Stream.")
    path = db_url[len(prefix) :]
    if not path:
        raise ValueError("SQLite URL must include a file path.")
    return path
