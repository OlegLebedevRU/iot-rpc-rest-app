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


def test_parse_cell_number_from_nested_rpc_payload():
    payload = {
        "id": "873e2e3e-66be-45a8-827d-b99a46031b16",
        "status": 1,
        "payload": {"dt": [{"cl": 88}]},
    }

    assert device_emulator.DeviceEmulator._parse_cell_number(payload) == 88


def test_event_timestamp_uses_centiseconds_when_fractional():
    now = datetime(
        2026,
        4,
        20,
        12,
        40,
        46,
        323612,
        tzinfo=timezone.utc,
    )

    payload = device_emulator.DeviceEmulator._build_event_message(
        13,
        10003,
        device_emulator.DeviceEmulator._cell_event_payload(88),
        now=now,
    )

    assert payload == {
        "101": 10003,
        "300": [{"304": 88}],
        "102": "2026-04-20T12:40:46.32+00:00",
        "200": 13,
    }


def test_event_timestamp_rounds_to_nearest_centisecond():
    now = datetime(
        2026,
        4,
        20,
        12,
        40,
        46,
        326000,
        tzinfo=timezone.utc,
    )

    payload = device_emulator.DeviceEmulator._build_event_message(
        13,
        10004,
        device_emulator.DeviceEmulator._cell_event_payload(88),
        now=now,
    )

    assert payload["102"] == "2026-04-20T12:40:46.33+00:00"
