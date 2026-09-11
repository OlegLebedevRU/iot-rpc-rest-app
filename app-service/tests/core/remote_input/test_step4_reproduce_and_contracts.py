from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from core.remote_input.leases import LeaseRegistry
from core.remote_input.mqtt_bridge import handle_device_ctl_message
from core.remote_input.pending import PendingCommandRegistry
from core.remote_input.presence import PresenceRegistry
from core.remote_input.publisher import send_ctl_command
from core.remote_input.rate_limit import RateLimiter
from core.remote_input.schemas import (
    CtlAck,
    CtlLeaseRenew,
    CtlStreamEvent,
)
from core.remote_input.service import RemoteInputService


def test_f1_ctl_lease_renew_wire_format_has_command_id():
    """F1: Wire format of CtlLeaseRenew must contain canonical command_id (UUID), not cmd_id."""
    renew = CtlLeaseRenew(
        command_id=UUID("831028de-8f1a-42b9-986a-6a2ee4e5e578"),
        lease_id=UUID("11111111-2222-3333-4444-555555555555"),
        ttl_sec=60,
        expires_at_ms=1726059600000,
        timestamp="2026-09-11T14:57:00Z",
    )
    data = renew.model_dump(mode="json")

    assert "command_id" in data
    assert data["command_id"] == "831028de-8f1a-42b9-986a-6a2ee4e5e578"
    assert "cmd_id" not in data, (
        "Legacy cmd_id field must not be sent on wire to strict consumers"
    )
    assert data["v"] == 1
    assert data["type"] == "lease_renew"
    assert data["ttl_sec"] == 60
    assert data["expires_at_ms"] == 1726059600000


def test_ctl_lease_renew_legacy_cmd_id_input_compatibility():
    """CtlLeaseRenew must accept legacy cmd_id on input/parsing, but expose canonical command_id."""
    raw = {
        "v": 1,
        "type": "lease_renew",
        "cmd_id": "831028de-8f1a-42b9-986a-6a2ee4e5e578",
        "lease_id": "11111111-2222-3333-4444-555555555555",
        "ttl_sec": 60,
        "expires_at_ms": 1726059600000,
        "timestamp": "2026-09-11T14:57:00Z",
    }
    renew = CtlLeaseRenew.model_validate(raw)
    assert renew.command_id == UUID("831028de-8f1a-42b9-986a-6a2ee4e5e578")
    assert renew.cmd_id == UUID("831028de-8f1a-42b9-986a-6a2ee4e5e578")

    dumped = renew.model_dump(mode="json")
    assert dumped["command_id"] == "831028de-8f1a-42b9-986a-6a2ee4e5e578"
    assert "cmd_id" not in dumped


@pytest.mark.asyncio
async def test_publisher_boundary_sends_canonical_command_id():
    """Verify that send_ctl_command passes command_id in both message body and correlationData."""
    renew = CtlLeaseRenew(
        command_id=UUID("831028de-8f1a-42b9-986a-6a2ee4e5e578"),
        lease_id=UUID("11111111-2222-3333-4444-555555555555"),
        ttl_sec=60,
        expires_at_ms=1726059600000,
        timestamp="2026-09-11T14:57:00Z",
    )

    with patch(
        "core.remote_input.publisher.topic_publisher.publish", new_callable=AsyncMock
    ) as mock_pub:
        await send_ctl_command("SN773", renew, ttl_ms=60000)

        assert mock_pub.call_count == 1
        kwargs = mock_pub.call_args[1]
        body = kwargs["message"]
        assert "command_id" in body
        assert body["command_id"] == "831028de-8f1a-42b9-986a-6a2ee4e5e578"
        assert str(kwargs["correlation_id"]) == "831028de-8f1a-42b9-986a-6a2ee4e5e578"
        assert (
            kwargs["headers"]["correlationData"]
            == "831028de-8f1a-42b9-986a-6a2ee4e5e578"
        )


def test_ctl_ack_with_empty_command_id_rejected():
    """Terminal ACK with empty command_id must fail validation without fallback dummy UUID."""
    bad_ack = {
        "v": 1,
        "type": "ack",
        "command_id": "",
        "lease_id": "11111111-2222-3333-4444-555555555555",
        "sn": "SN773",
        "result": "injected",
    }
    with pytest.raises(ValidationError):
        CtlAck.model_validate(bad_ack)


@pytest.mark.asyncio
async def test_mqtt_bridge_diagnoses_empty_command_id_separately():
    """mqtt_bridge must log diagnostic for empty command_id without generating dummy UUID or crashing."""
    p_reg = PresenceRegistry()
    cmd_reg = PendingCommandRegistry()
    l_reg = LeaseRegistry()

    bad_payload = (
        '{"v":1,"type":"ack","command_id":"","lease_id":"11111111-2222-3333-4444-555555555555",'
        '"sn":"SN773","result":"renewed","terminal_time_ms":1234}'
    )

    with patch("core.remote_input.mqtt_bridge.log") as mock_log:
        handled = await handle_device_ctl_message(
            routing_key="dev.SN773.ctl",
            payload=bad_payload,
            p_registry=p_reg,
            cmd_registry=cmd_reg,
            l_registry=l_reg,
        )
        assert handled is False
        assert mock_log.warning.called
        log_str = str(mock_log.warning.call_args)
        assert "empty_command_id" in log_str or "reason" in log_str


@pytest.mark.asyncio
async def test_camera_lease_stream_mode_not_overwritten_to_desktop():
    """Re-acquire or upgrade of lease with active camera stream must NOT reset stream_mode to desktop."""
    leases = LeaseRegistry()
    lease = await leases.acquire(
        org_id=1,
        device_id=10,
        sn="SN773",
        owner_user_id="user1",
        owner_role="admin",
        ttl_sec=60,
        scope="stream",
        owner_session_id="sess_1",
    )
    # Camera stream started
    lease.stream_mode = "usb-camera"
    lease.selected_camera_id = "cam:1"

    # 1. Idempotent re-acquire
    reacquired = await leases.acquire(
        org_id=1,
        device_id=10,
        sn="SN773",
        owner_user_id="user1",
        owner_role="admin",
        ttl_sec=60,
        scope="stream",
        owner_session_id="sess_1",
    )
    assert reacquired.stream_mode == "usb-camera", (
        "Re-acquire must preserve existing camera stream_mode"
    )

    # 2. Scope upgrade to input
    upgraded = await leases.upgrade_scope(lease.lease_id, "input")
    assert upgraded.stream_mode == "usb-camera", (
        "Scope upgrade must preserve existing camera stream_mode"
    )


@pytest.mark.asyncio
async def test_release_idempotent_for_own_lease_no_double_side_effects():
    """Duplicate release of own lease must be safe and idempotent, but cross-tenant remains forbidden."""
    leases = LeaseRegistry()
    presence = PresenceRegistry()
    pending = PendingCommandRegistry()
    limiter = RateLimiter()
    service = RemoteInputService(
        leases=leases, presence=presence, pending=pending, limiter=limiter
    )

    lease = await leases.acquire(
        org_id=1,
        device_id=10,
        sn="SN773",
        owner_user_id="user1",
        owner_role="admin",
        ttl_sec=60,
        scope="input",
        owner_session_id="sess_1",
    )
    lease.stream_instance_id = uuid4()

    with patch(
        "core.remote_input.leases.send_ctl_command", new_callable=AsyncMock
    ) as mock_stop:
        # First release: should revoke and send stream_stop
        await service.release(
            lease_id=lease.lease_id,
            org_id=1,
            caller_user_id="user1",
            caller_session_id="sess_1",
        )
        assert mock_stop.call_count == 1
        assert lease.revoked_reason == "released"

        # Second release (duplicate): must NOT send another stream_stop and must not raise error
        await service.release(
            lease_id=lease.lease_id,
            org_id=1,
            caller_user_id="user1",
            caller_session_id="sess_1",
        )
        assert mock_stop.call_count == 1, (
            "Duplicate release must not resend StreamStopCommand"
        )

        # Cross-tenant release on already revoked lease must STILL be forbidden (403)
        with pytest.raises(HTTPException) as exc_info:
            await service.release(
                lease_id=lease.lease_id,
                org_id=999,  # Wrong tenant
                caller_user_id="user1",
                caller_session_id="sess_1",
            )
        assert exc_info.value.status_code == 403

        # Cross-owner release on already revoked lease must STILL be forbidden (403)
        with pytest.raises(HTTPException) as exc_info2:
            await service.release(
                lease_id=lease.lease_id,
                org_id=1,
                caller_user_id="user2",  # Wrong owner
                caller_session_id="sess_1",
            )
        assert exc_info2.value.status_code == 403


@pytest.mark.asyncio
async def test_stale_stream_event_old_epoch_does_not_clear_new_stream():
    """A stopped/failed stream_event from a previous stream instance must not clear a newly active stream."""
    leases = LeaseRegistry()
    presence = PresenceRegistry()
    pending = PendingCommandRegistry()

    lease = await leases.acquire(
        org_id=1,
        device_id=10,
        sn="SN773",
        owner_user_id="user1",
        owner_role="admin",
        ttl_sec=60,
        scope="stream",
    )
    new_stream_instance = uuid4()
    lease.stream_instance_id = new_stream_instance
    lease.stream_state = "running"
    lease.stream_mode = "desktop"

    old_stream_instance = uuid4()
    old_event = CtlStreamEvent(
        v=1,
        type="stream_event",
        sn="SN773",
        stream_instance_id=old_stream_instance,
        state="stopped",
        reason="normal_stop",
        timestamp=datetime.now(UTC).isoformat(),
    )

    await handle_device_ctl_message(
        routing_key="dev.SN773.ctl",
        payload=old_event.model_dump(mode="json"),
        p_registry=presence,
        cmd_registry=pending,
        l_registry=leases,
    )

    # Active lease stream must NOT be cleared by old epoch event
    assert lease.stream_instance_id == new_stream_instance
    assert lease.stream_state == "running"
    assert lease.stream_mode == "desktop"
