"""Task-scoped arbitration of certificate handover; no PIN/payload reads.

Broker validity is the certificate discriminator exposed by RabbitMQ, not a
cryptographic fingerprint. A task alone never authorizes overlapping sockets.
"""

import json
from datetime import UTC, datetime, timedelta
from enum import Enum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.integrations.rmq_admin_api import RmqAdminApi
from core.models.devices import Device, DeviceConnection
from core.models.device_tasks import DevTask, DevTaskStatus
from core.models.common import PersistentVariable

ROTATION_KEY = "certificate_rotation"
HANDOVER_SECONDS = 300


class Decision(Enum):
    UNCHANGED = "unchanged"
    ALLOW = "allow"
    BLOCK = "block"
    DEFER = "defer"


def validity_period(value: object) -> tuple[datetime, datetime] | None:
    if not isinstance(value, str) or len(value) > 128:
        return None
    try:
        start, end = (
            datetime.fromisoformat(v.replace("Z", "+00:00")) for v in value.split(" - ")
        )
        if start.tzinfo is None or end.tzinfo is None or start >= end:
            return None
        return start, end
    except TypeError, ValueError:
        return None


def subject_identity(value: object) -> tuple[str, str, str] | None:
    if not isinstance(value, str) or len(value) > 2048:
        return None
    fields = {}
    for part in value.split(","):
        key, sep, text = part.strip().partition("=")
        if key in {"CN", "O", "OU"}:
            if not sep or not text or key in fields:
                return None
            fields[key] = text
    if len(fields) != 3:
        return None
    return fields["CN"], fields["O"], fields["OU"]


def decide_handover(
    *,
    sn: str,
    device_id: int,
    previous: dict,
    candidate: dict,
    connections: list[dict] | None,
    task_id: str | None,
    now: datetime,
) -> tuple[Decision, dict | None]:
    """Pure decision. Permit consumption is serialized by the DB device lock."""
    after = candidate.get("peer_cert_validity")
    stored = previous.get(ROTATION_KEY) or {}
    if not isinstance(stored, dict):
        return Decision.BLOCK, None
    before = stored.get("current") or previous.get("peer_cert_validity")
    retired = stored.get("retired", [])
    if (
        not isinstance(retired, list)
        or len(retired) > 8
        or any(not validity_period(v) for v in retired)
    ):
        return Decision.BLOCK, None
    if after in retired:
        return Decision.BLOCK, None
    # Normal reconnect does not need a renewal permit or broker request.
    if before == after and not stored:
        return Decision.UNCHANGED, None
    if not before or not after:
        return Decision.UNCHANGED, None
    if connections is None:
        return Decision.DEFER, None
    matching = [c for c in connections if c.get("name") == candidate.get("conn_name")]
    if len(matching) != 1:
        return Decision.DEFER, None  # Closed/stale AMQP event is not a new live socket.
    current = matching[0]
    if (
        current.get("user") != sn
        or current.get("ssl") is not True
        or current.get("peer_cert_validity") != after
    ):
        return Decision.DEFER, None
    if any(c.get("peer_cert_validity") != after for c in connections):
        return (
            Decision.BLOCK,
            None,
        )  # An active old/unknown certificate is never exempt.
    identity = subject_identity(current.get("peer_cert_subject"))
    if not identity or identity != subject_identity(candidate.get("peer_cert_subject")):
        return Decision.DEFER, None
    if identity[0] != sn or identity[2] != str(device_id):
        return Decision.BLOCK, None
    if stored.get("current") == after:
        return Decision.ALLOW, stored
    if not task_id or stored.get("task_id") == task_id:
        return Decision.BLOCK, None
    if identity != subject_identity(previous.get("peer_cert_subject")):
        return Decision.BLOCK, None
    old_period, new_period = validity_period(before), validity_period(after)
    if not old_period or not new_period:
        return Decision.BLOCK, None
    if not (
        new_period[0] > old_period[0]
        and new_period[1] > old_period[1]
        and new_period[0] <= now < new_period[1]
    ):
        return Decision.BLOCK, None
    return Decision.ALLOW, {
        "current": after,
        "retired": (retired + [before])[-8:],
        "task_id": task_id,
        "accepted_at": now.isoformat(),
    }


async def arbitrate_renewal(
    session: AsyncSession,
    sn: str,
    candidate: dict,
) -> Decision:
    """Keep the device row locked through the caller's connection-state commit."""
    device = (
        await session.execute(
            select(Device)
            .where(Device.sn == sn, Device.is_deleted.is_(False))
            .with_for_update()
        )
    ).scalar_one_or_none()
    if device is None:
        return Decision.UNCHANGED
    row = (
        await session.execute(
            select(DeviceConnection)
            .where(DeviceConnection.device_id == device.device_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if row is None or row.is_blocked or not isinstance(row.details, dict):
        return Decision.UNCHANGED
    # Server-owned durable state is separate from telemetry: reconciliation
    # must never overwrite the retired generation or consumed task permit.
    key = f"renewal.collision.{device.device_id}"
    record = (
        await session.execute(
            select(PersistentVariable)
            .where(PersistentVariable.var_key == key)
            .with_for_update()
        )
    ).scalar_one_or_none()
    previous = dict(row.details)
    previous.pop(ROTATION_KEY, None)
    stored = None
    if record is not None:
        if not isinstance(record.var_val, str) or len(record.var_val) > 4096:
            return Decision.BLOCK
        try:
            stored = json.loads(record.var_val)
        except ValueError:
            return Decision.BLOCK
        if not isinstance(stored, dict):
            return Decision.BLOCK
        previous[ROTATION_KEY] = stored
    before = stored.get("current") if isinstance(stored, dict) else None
    before = before or previous.get("peer_cert_validity")
    after = candidate.get("peer_cert_validity")
    if not before or not after or (before == after and not previous.get(ROTATION_KEY)):
        return Decision.UNCHANGED
    now = datetime.now(UTC)
    task_id = None
    if before != after:
        # Only a task actually delivered by RSP, not a queued task or operator's
        # claim. A fixed window cannot be extended by reconnects or restarts.
        task = (
            await session.execute(
                select(DevTask.id)
                .join(DevTaskStatus, DevTaskStatus.task_id == DevTask.id)
                .where(
                    DevTask.device_id == device.device_id,
                    DevTask.method_code == 7011,
                    DevTask.is_deleted.is_(False),
                    DevTaskStatus.status == 2,
                    DevTask.created_at >= now - timedelta(seconds=HANDOVER_SECONDS),
                    DevTask.created_at <= now,
                    DevTaskStatus.expires_at > now,
                    DevTaskStatus.locked_at
                    >= now - timedelta(seconds=HANDOVER_SECONDS),
                    DevTaskStatus.locked_at <= now,
                )
                .order_by(DevTaskStatus.locked_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        task_id = str(task) if task else None
    connections = await RmqAdminApi.get_device_connections_strict(sn)
    decision, state = decide_handover(
        sn=sn,
        device_id=device.device_id,
        previous=previous,
        candidate=candidate,
        connections=connections,
        task_id=task_id,
        now=now,
    )
    if decision is Decision.ALLOW:
        encoded = json.dumps(state, separators=(",", ":"))
        if record is None:
            session.add(
                PersistentVariable(var_key=key, var_val=encoded, var_typ="JSON")
            )
        elif record.var_val != encoded:
            record.var_val = encoded
    return decision
