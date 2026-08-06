from __future__ import annotations

import json
from uuid import uuid4

import pytest

from core.diagnostics.mqtt_bridge import (
    extract_sn_from_output_routing_key,
    handle_device_output_message,
)
from core.diagnostics.schemas import DiagnosticSessionKind
from core.diagnostics.sessions import DiagnosticSession, DiagnosticsSessionRegistry


def test_extract_sn_from_output_routing_key_supports_mqtt_and_amqp_forms():
    assert extract_sn_from_output_routing_key("dev.SN001.out") == "SN001"
    assert extract_sn_from_output_routing_key("dev/SN001/out") == "SN001"
    assert extract_sn_from_output_routing_key("dev.SN001.res") is None
    assert extract_sn_from_output_routing_key("bad") is None


@pytest.mark.asyncio
async def test_handle_device_output_message_routes_valid_payload():
    registry = DiagnosticsSessionRegistry()
    session_id = uuid4()
    session = DiagnosticSession(
        sn="SN001",
        session_id=session_id,
        kind=DiagnosticSessionKind.EXEC,
        ttl_sec=60,
    )
    await registry.register(session)
    await session.queue.get()

    delivered = await handle_device_output_message(
        routing_key="dev.SN001.out",
        payload=json.dumps(
            {
                "session_id": str(session_id),
                "seq": 1,
                "kind": "stdout",
                "stream": "stdout",
                "data": "ok\n",
            }
        ).encode(),
        session_registry=registry,
    )

    assert delivered is True
    assert (await session.queue.get()).data == "ok\n"


@pytest.mark.asyncio
async def test_handle_device_output_message_drops_unknown_session():
    registry = DiagnosticsSessionRegistry()

    delivered = await handle_device_output_message(
        routing_key="dev.SN001.out",
        payload={
            "session_id": str(uuid4()),
            "seq": 1,
            "kind": "stdout",
            "stream": "stdout",
            "data": "ok\n",
        },
        session_registry=registry,
    )

    assert delivered is False


@pytest.mark.asyncio
async def test_handle_device_output_message_drops_invalid_payload():
    delivered = await handle_device_output_message(
        routing_key="dev.SN001.out",
        payload=b"not-json",
        session_registry=DiagnosticsSessionRegistry(),
    )

    assert delivered is False
