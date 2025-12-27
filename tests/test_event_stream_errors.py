from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from arp_standard_server import AuthSettings
from jarvis_event_stream.config import EventStreamConfig, event_stream_config_from_env
from jarvis_event_stream.errors import ValidationError
from jarvis_event_stream.service import create_app
from jarvis_event_stream.sqlite import SqliteEventStore
from jarvis_event_stream.utils import (
    DEFAULT_DEV_KEYCLOAK_ISSUER,
    auth_settings_from_env_or_dev_secure,
    decode_cursor,
)


def test_auth_settings_default(monkeypatch) -> None:
    for key in list(os.environ):
        if key.startswith("ARP_AUTH_"):
            monkeypatch.delenv(key, raising=False)
    settings = auth_settings_from_env_or_dev_secure()
    assert settings.mode == "required"
    assert settings.issuer == DEFAULT_DEV_KEYCLOAK_ISSUER


def test_auth_settings_from_env(monkeypatch) -> None:
    monkeypatch.setenv("ARP_AUTH_MODE", "disabled")
    settings = auth_settings_from_env_or_dev_secure()
    assert settings.mode == "disabled"


def test_decode_cursor_invalid() -> None:
    with pytest.raises(ValueError):
        decode_cursor("bad")


def test_config_from_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("JARVIS_EVENT_STORE_DB_URL", f"sqlite:///{tmp_path / 'events.sqlite'}")
    monkeypatch.setenv("JARVIS_EVENT_RETENTION_DAYS", "7")
    config = event_stream_config_from_env()
    assert config.db_url.endswith("events.sqlite")
    assert config.retention_days == 7


def test_append_events_validation(tmp_path) -> None:
    config = EventStreamConfig(db_url=f"sqlite:///{tmp_path / 'event_store.sqlite'}", retention_days=None)
    app = create_app(config, auth_settings=AuthSettings(mode="disabled"))
    client = TestClient(app)

    resp = client.post("/v1/run-events", json={"events": []})
    assert resp.status_code == 422


def test_append_events_missing_run_id(tmp_path) -> None:
    config = EventStreamConfig(db_url=f"sqlite:///{tmp_path / 'event_store.sqlite'}", retention_days=None)
    app = create_app(config, auth_settings=AuthSettings(mode="disabled"))
    client = TestClient(app)

    resp = client.post("/v1/run-events", json={"events": [{"type": "run_started"}]})
    assert resp.status_code == 422


def test_append_events_invalid_seq(tmp_path) -> None:
    config = EventStreamConfig(db_url=f"sqlite:///{tmp_path / 'event_store.sqlite'}", retention_days=None)
    app = create_app(config, auth_settings=AuthSettings(mode="disabled"))
    client = TestClient(app)

    resp = client.post("/v1/run-events", json={"events": [{"run_id": "run_1", "seq": "bad"}]})
    assert resp.status_code == 422


def test_append_events_conflict(tmp_path) -> None:
    config = EventStreamConfig(db_url=f"sqlite:///{tmp_path / 'event_store.sqlite'}", retention_days=None)
    app = create_app(config, auth_settings=AuthSettings(mode="disabled"))
    client = TestClient(app)

    resp = client.post("/v1/run-events", json={"events": [{"run_id": "run_1", "seq": 1}]})
    assert resp.status_code == 200

    resp = client.post("/v1/run-events", json={"events": [{"run_id": "run_1", "seq": 1}]})
    assert resp.status_code == 409


def test_invalid_cursor_returns_422(tmp_path) -> None:
    config = EventStreamConfig(db_url=f"sqlite:///{tmp_path / 'event_store.sqlite'}", retention_days=None)
    app = create_app(config, auth_settings=AuthSettings(mode="disabled"))
    client = TestClient(app)

    resp = client.get("/v1/runs/run_1/events", params={"cursor": "bad"})
    assert resp.status_code == 422


def test_list_events_requires_identifier(tmp_path) -> None:
    config = EventStreamConfig(db_url=f"sqlite:///{tmp_path / 'event_store.sqlite'}", retention_days=None)
    store = SqliteEventStore(config)

    with pytest.raises(ValidationError):
        store.list_events()


def test_retention_removes_old_events(tmp_path) -> None:
    config = EventStreamConfig(db_url=f"sqlite:///{tmp_path / 'event_store.sqlite'}", retention_days=1)
    store = SqliteEventStore(config)

    store.append_events(
        [
            {
                "run_id": "run_1",
                "seq": 1,
                "type": "run_started",
                "time": "2000-01-01T00:00:00+00:00",
            }
        ]
    )

    events = store.list_events(run_id="run_1", after_seq=0, limit=10)
    assert events == []
