"""Real aio-pika serialization must match strict camera MQTT5 metadata."""

import copy
from uuid import uuid4

from aio_pika.abc import DeliveryMode
from faststream.rabbit.parser import AioPikaParser
import pytest

from core.camera.runtime import CameraRuntime
from core.camera.runtime_wire import ADMISSION, validate

from .test_camera_cadence02 import fixture


def messages():
    offer = fixture("offer")
    base = {
        "v": 1,
        "camera_admission_revision": ADMISSION,
        "sn": offer["sn"],
        "issuer_epoch": offer["issuer_epoch"],
        "binding": offer["binding"],
        "admission_seq": 1,
        "readiness_nonce": str(uuid4()),
        "issued_at_ms": 10000,
        "expires_at_ms": 15000,
    }
    query = {**base, "type": "camera_readiness_query"}
    start = {
        **base,
        "type": "stream_start",
        "command_id": str(uuid4()),
        "lease_id": str(uuid4()),
        "stream_instance_id": str(uuid4()),
        "command_seq": 1,
        "mode": "usb-camera",
        "source_id": "cam:ip000001",
        "profile": "default",
        "expires_at_ms": 70000,
    }
    renew = {
        k: v for k, v in start.items() if k not in ("mode", "source_id", "profile")
    }
    renew.update(type="lease_renew", command_id=str(uuid4()), command_seq=2, ttl_sec=60)
    stop = {k: v for k, v in renew.items() if k != "ttl_sec"}
    stop.update(
        type="stream_stop", command_id=str(uuid4()), command_seq=3, expires_at_ms=15000
    )
    return [offer, fixture("commit"), query, start, renew, stop]


@pytest.mark.anyio
@pytest.mark.parametrize("index", range(6))
@pytest.mark.parametrize("remaining_ms", [1, 1234])
async def test_camera_publication_encodes_qos1_correlation_and_remaining_ms(
    monkeypatch, index, remaining_ms
):
    from core.topologys.declare import topic_publisher

    message = messages()[index]
    validate(message)
    original = copy.deepcopy(message)
    encoded = []
    shared_defaults = copy.deepcopy(topic_publisher._message_options)

    async def encode_only(**kwargs):
        assert kwargs.pop("routing_key") == f"srv.{message['sn']}.ctl"
        body = kwargs.pop("message")
        encoded.append(await AioPikaParser.encode_message(body, **kwargs))

    monkeypatch.setattr(topic_publisher, "publish", encode_only)
    await CameraRuntime.publish(message["sn"], message, remaining_ms)
    actual = encoded[0]
    assert actual.delivery_mode == DeliveryMode.PERSISTENT
    # RabbitMQ AMQP0.9.1 -> MQTT5 maps correlation_id shortstr to binary data.
    expected = message.get(
        "command_id", message.get("enrollment_id", message.get("readiness_nonce"))
    )
    correlation = actual.properties.correlation_id.encode("utf-8")
    assert correlation == expected.encode("ascii") and len(correlation) == 36
    assert actual.properties.headers == {
        "correlationData": expected,
        "ctl_type": message["type"],
    }
    assert actual.properties.expiration == str(remaining_ms)
    assert message == original  # No payload deadline or binding rewrite.
    assert topic_publisher._message_options == shared_defaults
    assert not shared_defaults.get("persist")  # Noncamera shared publisher unchanged.


@pytest.mark.anyio
@pytest.mark.parametrize("ttl", [0, -1, 60001, True, 1.5])
async def test_camera_invalid_transport_budget_is_never_published(monkeypatch, ttl):
    from core.topologys.declare import topic_publisher

    async def forbidden(**kwargs):
        raise AssertionError("expired/invalid camera budget must not be published")

    monkeypatch.setattr(topic_publisher, "publish", forbidden)
    with pytest.raises(ValueError, match="camera_transport_ttl_invalid"):
        await CameraRuntime.publish("fixture", messages()[0], ttl)
