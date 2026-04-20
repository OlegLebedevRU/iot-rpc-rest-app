from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "device_emulator.py"
SPEC = importlib.util.spec_from_file_location("device_emulator_module", MODULE_PATH)
device_emulator = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(device_emulator)


def test_cell_event_payload_matches_strict_protocol_shape():
    now = datetime(2026, 3, 3, 12, 41, 33, tzinfo=timezone(timedelta(hours=3)))

    payload = device_emulator.DeviceEmulator._build_event_message(
        13,
        20338,
        device_emulator.DeviceEmulator._cell_event_payload(12),
        now=now,
    )

    assert payload == {
        "101": 20338,
        "300": [{"304": 12}],
        "102": "2026-03-03T12:41:33+03:00",
        "200": 13,
    }


def test_cell_close_event_payload_matches_strict_protocol_shape():
    now = datetime(2026, 3, 3, 12, 41, 33, tzinfo=timezone(timedelta(hours=3)))

    payload = device_emulator.DeviceEmulator._build_event_message(
        14,
        20339,
        device_emulator.DeviceEmulator._cell_event_payload(12),
        now=now,
    )

    assert payload == {
        "101": 20339,
        "300": [{"304": 12}],
        "102": "2026-03-03T12:41:33+03:00",
        "200": 14,
    }
