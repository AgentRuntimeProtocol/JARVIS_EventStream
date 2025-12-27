from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from jarvis_event_stream import __main__ as main_mod


def test_load_uvicorn_missing(monkeypatch) -> None:
    def _fail_import(name: str):
        raise ImportError("missing")

    monkeypatch.setattr(main_mod.importlib, "import_module", _fail_import)
    with pytest.raises(SystemExit):
        main_mod._load_uvicorn()


def test_main_reload(monkeypatch) -> None:
    calls: dict[str, object] = {}

    def _run(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls["args"] = args
        calls["kwargs"] = kwargs

    dummy = SimpleNamespace(run=_run)
    monkeypatch.setattr(main_mod, "_load_uvicorn", lambda: dummy)
    monkeypatch.setenv("ARP_AUTH_MODE", "disabled")
    monkeypatch.setattr(sys, "argv", ["prog", "--reload", "--host", "0.0.0.0", "--port", "9004"])

    main_mod.main()

    assert calls["args"][0] == "jarvis_event_stream.app:app"
    assert calls["kwargs"]["reload"] is True
    assert calls["kwargs"]["host"] == "0.0.0.0"
    assert calls["kwargs"]["port"] == 9004


def test_main_no_reload(monkeypatch) -> None:
    calls: dict[str, object] = {}

    def _run(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls["args"] = args
        calls["kwargs"] = kwargs

    dummy = SimpleNamespace(run=_run)
    monkeypatch.setattr(main_mod, "_load_uvicorn", lambda: dummy)
    monkeypatch.setenv("ARP_AUTH_MODE", "disabled")
    monkeypatch.setattr(sys, "argv", ["prog", "--host", "127.0.0.1", "--port", "9005"])

    main_mod.main()

    assert isinstance(calls["args"][0], FastAPI)
    assert calls["kwargs"]["reload"] is False
    assert calls["kwargs"]["host"] == "127.0.0.1"
    assert calls["kwargs"]["port"] == 9005


def test_app_module(monkeypatch) -> None:
    monkeypatch.setenv("ARP_AUTH_MODE", "disabled")
    sys.modules.pop("jarvis_event_stream.app", None)
    module = importlib.import_module("jarvis_event_stream.app")
    assert hasattr(module, "app")
