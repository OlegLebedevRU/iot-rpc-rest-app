import pathlib
import pytest
from unittest.mock import MagicMock
from alembic import op
import importlib.util


def test_alembic_lwt_flags_migration_upgrade_and_downgrade(monkeypatch):
    migration_path = (
        pathlib.Path(__file__).parent.parent.parent
        / "alembic"
        / "versions"
        / "2026_08_26_0001_add_device_connection_lwt_flags.py"
    )
    spec = importlib.util.spec_from_file_location("migration_lwt_flags", migration_path)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    mock_add_column = MagicMock()
    mock_create_index = MagicMock()
    mock_drop_index = MagicMock()
    mock_drop_column = MagicMock()

    monkeypatch.setattr(op, "add_column", mock_add_column)
    monkeypatch.setattr(op, "create_index", mock_create_index)
    monkeypatch.setattr(op, "drop_index", mock_drop_index)
    monkeypatch.setattr(op, "drop_column", mock_drop_column)

    mod.upgrade()
    assert mock_add_column.call_count == 2
    assert mock_create_index.call_count == 1

    mod.downgrade()
    assert mock_drop_index.call_count == 1
    assert mock_drop_column.call_count == 2


def test_alembic_org_api_keys_migration_upgrade_and_downgrade(monkeypatch):
    migration_path = (
        pathlib.Path(__file__).parent.parent.parent
        / "alembic"
        / "versions"
        / "2026_08_27_0002_add_org_api_keys_table_and_seed.py"
    )
    spec = importlib.util.spec_from_file_location("migration_org_api_keys", migration_path)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    mock_create_table = MagicMock()
    mock_create_index = MagicMock()
    mock_drop_index = MagicMock()
    mock_drop_table = MagicMock()
    mock_bind = MagicMock()

    monkeypatch.setattr(op, "create_table", mock_create_table)
    monkeypatch.setattr(op, "create_index", mock_create_index)
    monkeypatch.setattr(op, "drop_index", mock_drop_index)
    monkeypatch.setattr(op, "drop_table", mock_drop_table)
    monkeypatch.setattr(op, "get_bind", lambda: mock_bind)

    mod.upgrade()
    assert mock_create_table.call_count == 1
    assert mock_create_index.call_count == 1

    mod.downgrade()
    assert mock_drop_index.call_count == 1
    assert mock_drop_table.call_count == 1
