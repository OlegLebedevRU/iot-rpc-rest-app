from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path

import pytest


os.environ.setdefault(
    "APP_CONFIG__FASTSTREAM__URL", "amqp://user:pass@localhost:5672//"
)
os.environ.setdefault(
    "APP_CONFIG__DB__URL", "postgresql+asyncpg://user:pass@localhost:5432/postgres"
)
os.environ.setdefault("APP_CONFIG__AUTH__API_KEYS", "test:1")
os.environ.setdefault("APP_CONFIG__LEO4__URL", "http://localhost")
os.environ.setdefault("APP_CONFIG__LEO4__API_KEY", "x")
os.environ.setdefault("APP_CONFIG__LEO4__ADMIN_URL", "http://localhost")
os.environ.setdefault("APP_CONFIG__LEO4__CERT_URL", "http://localhost")

logging.handlers.RotatingFileHandler = (
    lambda *args, **kwargs: logging.NullHandler()
)

_ORIGINAL_PATH_MKDIR = Path.mkdir


def _safe_test_mkdir(self, mode=0o777, parents=False, exist_ok=False):
    normalized = str(self).replace("\\", "/")
    if normalized.endswith("/var/log/app"):
        return None
    return _ORIGINAL_PATH_MKDIR(
        self, mode=mode, parents=parents, exist_ok=exist_ok
    )


Path.mkdir = _safe_test_mkdir

collect_ignore_glob = ["api/v1/test_postamat.py"]


APP_SERVICE_DIR = Path(__file__).resolve().parents[1]
app_service_path = str(APP_SERVICE_DIR)

if app_service_path not in sys.path:
    sys.path.insert(0, app_service_path)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "asyncio" in item.keywords and "anyio" not in item.keywords:
            item.add_marker(pytest.mark.anyio)


