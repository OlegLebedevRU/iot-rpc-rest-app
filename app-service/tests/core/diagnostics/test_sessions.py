from __future__ import annotations

from uuid import uuid4

import pytest

from core.diagnostics.schemas import (
    BackendMessageType,
    DeviceOutputEnvelope,
    DiagnosticSessionKind,
)
from core.diagnostics.sessions import DiagnosticSession, DiagnosticsSessionRegistry


@pytest.mark.asyncio
async def test_chunk_with_active_session_is_delivered_to_queue():
    registry = DiagnosticsSessionRegistry()
    session_id = uuid4()
    session = DiagnosticSession(
        sn="SN001",
        session_id=session_id,
        kind=DiagnosticSessionKind.LIVE_LOG,
        ttl_sec=300,
    )
    await registry.register(session)
    await session.queue.get()  # initial started status

    delivered = await registry.route_output(
        "SN001",
        DeviceOutputEnvelope(
            session_id=session_id,
            seq=1,
            kind="stdout",
            stream="stdout",
            data="hello\n",
        ),
    )

    message = await session.queue.get()
    assert delivered is True
    assert message.type is BackendMessageType.OUTPUT
    assert message.sn == "SN001"
    assert message.session_id == session_id
    assert message.data == "hello\n"


@pytest.mark.asyncio
async def test_chunk_with_unknown_session_is_dropped():
    registry = DiagnosticsSessionRegistry()

    delivered = await registry.route_output(
        "SN001",
        DeviceOutputEnvelope(
            session_id=uuid4(),
            seq=1,
            kind="stdout",
            stream="stdout",
            data="hello\n",
        ),
    )

    assert delivered is False


@pytest.mark.asyncio
async def test_chunk_with_wrong_sn_is_not_delivered():
    registry = DiagnosticsSessionRegistry()
    session_id = uuid4()
    session = DiagnosticSession(
        sn="SN001",
        session_id=session_id,
        kind=DiagnosticSessionKind.LIVE_LOG,
        ttl_sec=300,
    )
    await registry.register(session)
    await session.queue.get()

    delivered = await registry.route_output(
        "SN002",
        DeviceOutputEnvelope(
            session_id=session_id,
            seq=1,
            kind="stdout",
            stream="stdout",
            data="hello\n",
        ),
    )

    assert delivered is False
    assert session.queue.empty()


@pytest.mark.asyncio
async def test_session_cleanup_removes_route():
    registry = DiagnosticsSessionRegistry()
    session_id = uuid4()
    await registry.register(
        DiagnosticSession(
            sn="SN001",
            session_id=session_id,
            kind=DiagnosticSessionKind.EXEC,
            ttl_sec=300,
        )
    )

    removed = await registry.remove("SN001", session_id)
    delivered = await registry.route_output(
        "SN001",
        DeviceOutputEnvelope(
            session_id=session_id,
            seq=1,
            kind="stdout",
            stream="stdout",
            data="hello\n",
        ),
    )

    assert removed is not None
    assert delivered is False
