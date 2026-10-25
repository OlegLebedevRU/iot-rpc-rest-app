"""Exercise real option selection and entrypoint wiring without Unix Gunicorn."""

import importlib.util
from pathlib import Path
import runpy
import sys
from types import ModuleType, SimpleNamespace

import pytest

from core.config import settings

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def options(monkeypatch):
    # Only the platform-specific logger dependency is substituted. The actual
    # production function and run_main entrypoint execute unchanged below.
    package = ModuleType("_camera_gunicorn_options")
    package.__path__ = []
    logger = ModuleType("_camera_gunicorn_options.logger")
    logger.GunicornLogger = type("Logger", (), {})
    monkeypatch.setitem(sys.modules, package.__name__, package)
    monkeypatch.setitem(sys.modules, logger.__name__, logger)
    spec = importlib.util.spec_from_file_location(
        package.__name__ + ".app_options",
        ROOT / "app-service/core/gunicorn/app_options.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.get_app_options


def test_camera_issuer_avoids_request_recycling_without_changing_other_options(options):
    arguments = dict(
        host="127.0.0.1", port=8123, timeout=60, workers=3, log_level="info"
    )
    historical = options(**arguments)
    disabled = options(**arguments, camera_runtime_enabled=False)
    enabled = options(**arguments, camera_runtime_enabled=True)
    assert historical == disabled
    assert (historical["max_requests"], historical["max_requests_jitter"]) == (
        1000,
        100,
    )
    assert (enabled["max_requests"], enabled["max_requests_jitter"]) == (0, 0)
    assert {key for key in enabled if enabled[key] != disabled[key]} == {
        "max_requests",
        "max_requests_jitter",
    }


@pytest.mark.parametrize("enabled", [False, True])
def test_actual_entrypoint_passes_existing_camera_gate(monkeypatch, options, enabled):
    calls = []

    class Application:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def run(self):
            calls.append("run")

    application = object()
    monkeypatch.setattr(settings.camera, "monotonic_runtime_enabled", enabled)
    monkeypatch.setitem(
        sys.modules,
        "core.gunicorn",
        SimpleNamespace(Application=Application, get_app_options=options),
    )
    monkeypatch.setitem(sys.modules, "main", SimpleNamespace(main_app=application))
    entrypoint = runpy.run_path(str(ROOT / "app-service/run_main.py"))
    entrypoint["main"]()
    assert calls[0]["application"] is application and calls[1:] == ["run"]
    assert calls[0]["options"]["max_requests"] == (0 if enabled else 1000)
    assert calls[0]["options"]["max_requests_jitter"] == (0 if enabled else 100)
