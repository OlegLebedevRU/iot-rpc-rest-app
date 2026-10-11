"""Camera commands reject unsafe envelopes and snapshots use the gauge path."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from core.config import WebhookConfigModel
from core.schemas.device_tasks import TaskCreate
from core.services import device_events_collect as collector_module


def task(method_code, payload):
    return TaskCreate(
        ext_task_id="camera-test",
        device_id=4619,
        method_code=method_code,
        ttl=1,
        payload=payload,
    )


def write_payload(**overrides):
    return {
        "dt": [
            {
                "expected_revision": "a" * 64,
                "patch": {"video0": {"bitrate": 1024}},
                **overrides,
            }
        ]
    }


def test_camera_read_defaults_and_write_envelope():
    read = task(160, {"dt": [{}]}).payload["dt"][0]
    assert read == {"camera_id": "cam:ip000001", "timeout_ms": 5000}
    write = task(161, write_payload()).payload["dt"][0]
    assert write["patch"] == {"video0": {"bitrate": 1024}}
    assert write["allow_disruptive"] is False and write["dry_run"] is False


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"dt": []},
        {"dt": [{}, {}]},
        {"dt": [{"url": "http://example.com"}]},
        {"dt": [{"camera_id": "other"}]},
        {"dt": [{"timeout_ms": 0}]},
        {"dt": [{"timeout_ms": 15001}]},
        {"dt": [{"timeout_ms": True}]},
        {"dt": [{"timeout_ms": "5000"}]},
        {"dt": [{}], "extra": True},
    ],
)
def test_camera_read_rejects_invalid_envelopes(payload):
    with pytest.raises(ValidationError):
        task(160, payload)


@pytest.mark.parametrize(
    "overrides",
    [
        {"expected_revision": "bad"},
        {"patch": {}},
        {"patch": {"isp": {}}},
        {"patch": {"outgoing": {"server": "udp://example.com:1234"}}},
        {"patch": {"video0": {"bitrate": 1024, "codec": "h265"}}},
        {"patch": {"video0": {"bitrate": None}}},
        {"patch": {"video0": {"bitrate": []}}},
        {"patch": {"video0": {"bitrate": float("nan")}}},
        {"patch": {"video0": {"bitrate": float("inf")}}},
        {"patch": {"video0": {"rcMode": "x" * 65}}},
        {"allow_disruptive": "true"},
        {"dry_run": 1},
        {"shell": "reboot"},
        {"password": "not-a-camera-parameter"},
    ],
)
def test_camera_write_rejects_invalid_or_mixed_patch(overrides):
    with pytest.raises(ValidationError):
        task(161, write_payload(**overrides))


def test_write_requires_revision_and_legacy_methods_are_unchanged():
    with pytest.raises(ValidationError):
        task(161, {"dt": [{"patch": {"video0": {"fps": 15}}}]})
    assert task(51, {"dt": [{"cl": 1}]}).payload == {"dt": [{"cl": 1}]}


@pytest.mark.parametrize("mode", ["auto", "day", "night"])
def test_day_night_envelope_and_defaults(mode):
    payload = task(
        162, {"dt": [{"expected_revision": "a" * 64, "mode": mode}]}
    ).payload["dt"][0]
    assert payload["mode"] == mode
    assert payload["camera_id"] == "cam:ip000001"
    assert payload["allow_disruptive"] is False and payload["dry_run"] is False
    assert task(
        161, write_payload(patch={"nightMode": {"lightMonitor": True}})
    ).payload["dt"][0]["patch"] == {"nightMode": {"lightMonitor": True}}


@pytest.mark.parametrize(
    "extra",
    [
        {"mode": "toggle"},
        {"mode": True},
        {"expected_revision": "A" * 64},
        {"allow_disruptive": "true"},
        {"dry_run": 1},
        {"url": "/night/toggle"},
        {"patch": {"nightMode": {"irCutPin1": 12}}},
    ],
)
def test_day_night_rejects_unsafe_or_invalid_envelopes(extra):
    with pytest.raises(ValidationError):
        task(162, {"dt": [{"expected_revision": "a" * 64, "mode": "day", **extra}]})


@pytest.mark.parametrize("value", ["true", 1, None])
def test_monitor_requires_strict_boolean(value):
    with pytest.raises(ValidationError):
        task(161, write_payload(patch={"nightMode": {"lightMonitor": value}}))


@pytest.mark.parametrize("preset", ["medium", "hd"])
def test_quality_preset_envelope(preset):
    request = task(163, {"dt": [{"preset": preset, "expected_revision": "a" * 64}]})
    item = request.payload["dt"][0]
    assert item["timeout_ms"] == 15000 and item["preset"] == preset
    assert item["dry_run"] is False and item["allow_disruptive"] is False


@pytest.mark.parametrize(
    "extra",
    [
        {"preset": "custom"},
        {"preset": 1},
        {"patch": {"video0": {"codec": "h265"}}},
        {"allow_disruptive": "true"},
        {"expected_revision": "A" * 64},
        {"url": "http://camera"},
    ],
)
def test_quality_preset_rejects_unapproved_input(extra):
    with pytest.raises(ValidationError):
        task(163, {"dt": [{"preset": "hd", "expected_revision": "a" * 64, **extra}]})


@pytest.mark.parametrize("action", ["on", "off", "restart"])
def test_power_envelope_without_camera_config_revision(action):
    item = task(164, {"dt": [{"action": action, "expected_power_on": True}]}).payload[
        "dt"
    ][0]
    assert item["timeout_ms"] == 10000
    assert item["expected_power_on"] is True
    assert item["allow_disruptive"] is False and item["dry_run"] is False


@pytest.mark.parametrize(
    "extra",
    [
        {"action": "toggle"},
        {"action": 1},
        {"expected_power_on": 1},
        {"expected_power_on": "true"},
        {"expected_revision": "a" * 64},
        {"pin": 3},
        {"off_ms": 3000},
        {"url": "http://camera"},
        {"allow_disruptive": 1},
        {"dry_run": "true"},
    ],
)
def test_power_rejects_unsafe_input(extra):
    with pytest.raises(ValidationError):
        task(164, {"dt": [{"action": "restart", "expected_power_on": True, **extra}]})


def test_power_requires_observed_output_state():
    with pytest.raises(ValidationError):
        task(164, {"dt": [{"action": "on"}]})


@pytest.mark.anyio
async def test_camera_snapshot_updates_gauge_without_history_webhook_or_eva(
    monkeypatch,
):
    monkeypatch.setattr(collector_module.settings, "webhook", WebhookConfigModel())
    payload = {
        "200": 84,
        "300": [
            {
                "450": {
                    "schema_version": 1,
                    "snapshot_id": "sample",
                    "cameras": [
                        {
                            "camera_id": "cam:ip000001",
                            "status": "read_only",
                            "config": {"video0": {"fps": 15}},
                            "capabilities": {"write": False},
                        }
                    ],
                }
            }
        ],
    }
    lookup = AsyncMock(return_value=4619)
    gauge = AsyncMock()
    history = AsyncMock()
    webhook = AsyncMock()
    eva = AsyncMock()
    monkeypatch.setattr(collector_module.DeviceRepo, "get_device_id", lookup)
    monkeypatch.setattr(collector_module.DeviceRepo, "upsert_gauge", gauge)
    monkeypatch.setattr(collector_module.EventRepository, "add_event", history)
    monkeypatch.setattr(collector_module.topic_publisher, "publish", webhook)
    monkeypatch.setattr(collector_module, "send_eva", eva)
    session = object()
    message = SimpleNamespace(
        headers={"event_type_code": "84", "dev_event_id": "7"},
        body=json.dumps(payload).encode(),
    )
    await collector_module.DeviceEventsCollect(session, "test-sn", org_id=1).add(
        message
    )
    gauge.assert_awaited_once_with(
        session, org_id=1, device_id=4619, type="84", gauges=payload
    )
    history.assert_not_awaited()
    webhook.assert_not_awaited()
    eva.assert_not_awaited()


def test_camera_gauge_is_activity_billing_and_env_override_remains_explicit():
    from core.services.billing_utils import evt_billing_counter_type

    defaults = WebhookConfigModel().gauge_event_types
    assert 44 in defaults and 84 in defaults
    assert evt_billing_counter_type(84, defaults) == "activity"
    assert WebhookConfigModel(gauge_event_types=[44]).gauge_event_types == [44]
