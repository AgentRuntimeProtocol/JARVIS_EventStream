from __future__ import annotations

import json

from fastapi.testclient import TestClient
from arp_standard_server import AuthSettings

from jarvis_event_stream.config import EventStreamConfig
from jarvis_event_stream.service import create_app


def test_append_and_stream_events(tmp_path) -> None:
    config = EventStreamConfig(db_url=f"sqlite:///{tmp_path / 'event_store.sqlite'}", retention_days=None)
    app = create_app(config, auth_settings=AuthSettings(mode="disabled"))
    client = TestClient(app)

    resp = client.post(
        "/v1/run-events",
        json={"events": [{"run_id": "run_1", "type": "run_started"}]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"][0]["seq"] == 1
    assert body["next_seq_by_run"]["run_1"] == 2

    client.post(
        "/v1/run-events",
        json={"events": [{"run_id": "run_1", "node_run_id": "node_1", "type": "atomic_executed"}]},
    )

    stream_resp = client.get("/v1/runs/run_1/events")
    assert stream_resp.status_code == 200
    lines = [line for line in stream_resp.text.strip().splitlines() if line]
    assert len(lines) == 2
    payloads = [json.loads(line) for line in lines]
    assert payloads[0]["seq"] == 1
    assert payloads[1]["seq"] == 2

    node_stream = client.get("/v1/node-runs/node_1/events")
    assert node_stream.status_code == 200
    node_lines = [line for line in node_stream.text.strip().splitlines() if line]
    assert len(node_lines) == 1
    assert json.loads(node_lines[0])["node_run_id"] == "node_1"
