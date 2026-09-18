from __future__ import annotations

import asyncio
import hashlib
import inspect
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.logging_config import setup_module_logger
from core.models.db_helper import db_helper
from core.models.devices import Device, DeviceOrgBind
from core.models.remote_sessions import RemoteSession, RemoteSessionEvent
from core.schemas.remote_sessions import (
    RemoteSessionCreate,
    RemoteSessionEventFeedResponse,
    RemoteSessionEventItem,
    RemoteSessionEventType,
    RemoteSessionLifecycleState,
    RemoteSessionReconciliationResponse,
    RemoteSessionResponse,
    RemoteSessionStop,
    validate_no_commercial_fields,
)

log = setup_module_logger(__name__, "remote_session_events.log")


class RemoteSessionEventService:
    """Service for managing durable remote session facts, event feed, and reconciliation."""

    async def resolve_device_and_tenant(
        self,
        session: AsyncSession,
        sn: str,
        tenant_id: int | None = None,
        device_id: int | None = None,
    ) -> tuple[int | None, int | None]:
        """Resolve device_id and tenant_id from Device and DeviceOrgBind if not provided."""
        resolved_device_id = device_id
        resolved_tenant_id = tenant_id

        if resolved_device_id is None or resolved_tenant_id is None:
            try:
                stmt = (
                    select(Device.device_id, DeviceOrgBind.org_id)
                    .outerjoin(DeviceOrgBind, Device.device_id == DeviceOrgBind.device_id)
                    .where(Device.sn == sn)
                    .limit(1)
                )
                exec_result = await session.execute(stmt)
                first_fn = getattr(exec_result, "first", None)
                if callable(first_fn):
                    res = first_fn()
                    if inspect.iscoroutine(res):
                        res = await res
                    if (
                        res is not None
                        and not inspect.iscoroutine(res)
                        and isinstance(res, (tuple, list))
                    ):
                        if resolved_device_id is None and len(res) > 0:
                            resolved_device_id = res[0]
                        if resolved_tenant_id is None and len(res) > 1 and res[1] is not None:
                            resolved_tenant_id = res[1]
            except Exception as e:
                log.debug("Device/tenant resolution fallback for sn=%s: %s", sn, e)

        return resolved_tenant_id, resolved_device_id

    async def record_event(
        self,
        session: AsyncSession,
        *,
        event_type: str,
        sn: str,
        event_id: str | None = None,
        occurred_at: datetime | None = None,
        tenant_id: int | None = None,
        terminal_id: str | None = None,
        device_id: int | None = None,
        session_id: str | None = None,
        session_type: str | None = None,
        event_version: str = "1.0.0",
        lifecycle_state: str | None = None,
        reason: str | None = None,
        operation_id: str | None = None,
        correlation_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> RemoteSessionEvent:
        """Record an immutable event into the durable event feed with idempotency deduplication."""
        # 1. Idempotency check by event_id
        if event_id:
            try:
                existing = await session.scalar(
                    select(RemoteSessionEvent).where(RemoteSessionEvent.event_id == event_id)
                )
                if (
                    existing is not None
                    and not asyncio.iscoroutine(existing)
                    and getattr(existing, "cursor", None) is not None
                ):
                    log.info("Duplicate event ignored by event_id=%s (cursor=%s)", event_id, existing.cursor)
                    return existing
            except Exception as e:
                log.debug("Scalar check failed for event_id=%s: %s", event_id, e, exc_info=True)

        # 2. Idempotency check by operation_id + event_type
        if operation_id:
            try:
                existing_op = await session.scalar(
                    select(RemoteSessionEvent).where(
                        RemoteSessionEvent.operation_id == operation_id,
                        RemoteSessionEvent.event_type == event_type,
                    )
                )
                if (
                    existing_op is not None
                    and not asyncio.iscoroutine(existing_op)
                    and getattr(existing_op, "cursor", None) is not None
                ):
                    log.info(
                        "Duplicate event ignored by operation_id=%s event_type=%s (cursor=%s)",
                        operation_id,
                        event_type,
                        existing_op.cursor,
                    )
                    return existing_op
            except Exception as e:
                log.debug("Scalar check failed for operation_id=%s: %s", operation_id, e, exc_info=True)

        # 3. Payload validation
        clean_payload = dict(payload) if payload else {}
        validate_no_commercial_fields(clean_payload)

        # 4. Resolve identifiers if missing
        res_tenant_id, res_device_id = await self.resolve_device_and_tenant(
            session, sn=sn, tenant_id=tenant_id, device_id=device_id
        )

        event_uid = event_id or f"evt_{uuid4().hex}"
        evt_occurred_at = occurred_at or datetime.now(UTC)

        event_record = RemoteSessionEvent(
            event_id=event_uid,
            occurred_at=evt_occurred_at,
            tenant_id=res_tenant_id,
            terminal_id=terminal_id,
            device_id=res_device_id,
            sn=sn,
            session_id=session_id,
            session_type=session_type,
            event_type=event_type,
            event_version=event_version,
            lifecycle_state=lifecycle_state,
            reason=reason,
            operation_id=operation_id,
            correlation_id=correlation_id,
            payload=clean_payload,
        )

        session.add(event_record)
        await session.flush()
        log.debug(
            "Recorded remote session event cursor=%s event_id=%s type=%s sn=%s",
            event_record.cursor,
            event_record.event_id,
            event_record.event_type,
            sn,
        )
        return event_record

    # ── Specialized Event Recorders for Mandatory Events ────────────────────────

    async def record_device_online(
        self,
        session: AsyncSession,
        *,
        sn: str,
        tenant_id: int | None = None,
        terminal_id: str | None = None,
        device_id: int | None = None,
        operation_id: str | None = None,
        correlation_id: str | None = None,
        occurred_at: datetime | None = None,
        payload: dict[str, Any] | None = None,
    ) -> RemoteSessionEvent:
        return await self.record_event(
            session,
            event_type=RemoteSessionEventType.DEVICE_ONLINE,
            sn=sn,
            tenant_id=tenant_id,
            terminal_id=terminal_id,
            device_id=device_id,
            lifecycle_state="online",
            operation_id=operation_id,
            correlation_id=correlation_id,
            occurred_at=occurred_at,
            payload=payload,
        )

    async def record_device_provisioned(
        self,
        session: AsyncSession,
        *,
        sn: str,
        tenant_id: int,
        terminal_id: int | str,
        device_id: int,
        operation_id: str,
        correlation_id: str | None = None,
        occurred_at: datetime | None = None,
        payload: dict[str, Any] | None = None,
    ) -> RemoteSessionEvent:
        event_payload = {
            "operation_id": operation_id,
            "tenant_id": tenant_id,
            "terminal_id": int(terminal_id),
            "device_id": device_id,
            "sn": sn,
            "status": "provisioned",
        }
        if payload:
            event_payload.update(payload)
        return await self.record_event(
            session,
            event_type=RemoteSessionEventType.DEVICE_PROVISIONED,
            sn=sn,
            tenant_id=tenant_id,
            terminal_id=str(terminal_id),
            device_id=device_id,
            lifecycle_state="provisioned",
            reason="provisioned_successfully",
            operation_id=operation_id,
            correlation_id=correlation_id,
            occurred_at=occurred_at,
            payload=event_payload,
        )

    async def record_device_provision_failed(
        self,
        session: AsyncSession,
        *,
        sn: str,
        tenant_id: int,
        terminal_id: int | str,
        device_id: int | None = None,
        operation_id: str,
        correlation_id: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        occurred_at: datetime | None = None,
        payload: dict[str, Any] | None = None,
    ) -> RemoteSessionEvent:
        event_payload = {
            "operation_id": operation_id,
            "tenant_id": tenant_id,
            "terminal_id": int(terminal_id),
            "device_id": device_id,
            "sn": sn,
            "status": "failed",
            "error_code": error_code,
            "error_message": error_message,
        }
        if payload:
            event_payload.update(payload)
        return await self.record_event(
            session,
            event_type=RemoteSessionEventType.DEVICE_PROVISION_FAILED,
            sn=sn,
            tenant_id=tenant_id,
            terminal_id=str(terminal_id),
            device_id=device_id,
            lifecycle_state="failed",
            reason=error_code or "provisioning_failed",
            operation_id=operation_id,
            correlation_id=correlation_id,
            occurred_at=occurred_at,
            payload=event_payload,
        )

    async def record_session_start_requested(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        sn: str,
        session_type: str,
        tenant_id: int | None = None,
        terminal_id: str | None = None,
        device_id: int | None = None,
        requested_by_user_id: str | None = None,
        operation_id: str | None = None,
        correlation_id: str | None = None,
        occurred_at: datetime | None = None,
        payload: dict[str, Any] | None = None,
    ) -> RemoteSessionEvent:
        event_payload = dict(payload or {})
        if requested_by_user_id:
            event_payload["requested_by_user_id"] = requested_by_user_id

        return await self.record_event(
            session,
            event_type=RemoteSessionEventType.REMOTE_SESSION_START_REQUESTED,
            sn=sn,
            session_id=session_id,
            session_type=session_type,
            tenant_id=tenant_id,
            terminal_id=terminal_id,
            device_id=device_id,
            lifecycle_state=RemoteSessionLifecycleState.REQUESTED,
            operation_id=operation_id,
            correlation_id=correlation_id,
            occurred_at=occurred_at,
            payload=event_payload,
        )

    async def record_session_active(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        sn: str,
        session_type: str,
        tenant_id: int | None = None,
        terminal_id: str | None = None,
        device_id: int | None = None,
        operation_id: str | None = None,
        correlation_id: str | None = None,
        occurred_at: datetime | None = None,
        payload: dict[str, Any] | None = None,
    ) -> RemoteSessionEvent:
        return await self.record_event(
            session,
            event_type=RemoteSessionEventType.REMOTE_SESSION_ACTIVE,
            sn=sn,
            session_id=session_id,
            session_type=session_type,
            tenant_id=tenant_id,
            terminal_id=terminal_id,
            device_id=device_id,
            lifecycle_state=RemoteSessionLifecycleState.ACTIVE,
            operation_id=operation_id,
            correlation_id=correlation_id,
            occurred_at=occurred_at,
            payload=payload,
        )

    async def record_session_stop_requested(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        sn: str,
        session_type: str,
        tenant_id: int | None = None,
        terminal_id: str | None = None,
        device_id: int | None = None,
        reason: str | None = "user_requested",
        operation_id: str | None = None,
        correlation_id: str | None = None,
        occurred_at: datetime | None = None,
        payload: dict[str, Any] | None = None,
    ) -> RemoteSessionEvent:
        return await self.record_event(
            session,
            event_type=RemoteSessionEventType.REMOTE_SESSION_STOP_REQUESTED,
            sn=sn,
            session_id=session_id,
            session_type=session_type,
            tenant_id=tenant_id,
            terminal_id=terminal_id,
            device_id=device_id,
            lifecycle_state=RemoteSessionLifecycleState.STOPPING,
            reason=reason,
            operation_id=operation_id,
            correlation_id=correlation_id,
            occurred_at=occurred_at,
            payload=payload,
        )

    async def record_session_closed(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        sn: str,
        session_type: str,
        tenant_id: int | None = None,
        terminal_id: str | None = None,
        device_id: int | None = None,
        reason: str | None = "closed",
        operation_id: str | None = None,
        correlation_id: str | None = None,
        occurred_at: datetime | None = None,
        payload: dict[str, Any] | None = None,
    ) -> RemoteSessionEvent:
        return await self.record_event(
            session,
            event_type=RemoteSessionEventType.REMOTE_SESSION_CLOSED,
            sn=sn,
            session_id=session_id,
            session_type=session_type,
            tenant_id=tenant_id,
            terminal_id=terminal_id,
            device_id=device_id,
            lifecycle_state=RemoteSessionLifecycleState.CLOSED,
            reason=reason,
            operation_id=operation_id,
            correlation_id=correlation_id,
            occurred_at=occurred_at,
            payload=payload,
        )

    async def record_session_failed(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        sn: str,
        session_type: str,
        tenant_id: int | None = None,
        terminal_id: str | None = None,
        device_id: int | None = None,
        reason: str | None = "failed",
        operation_id: str | None = None,
        correlation_id: str | None = None,
        occurred_at: datetime | None = None,
        payload: dict[str, Any] | None = None,
    ) -> RemoteSessionEvent:
        return await self.record_event(
            session,
            event_type=RemoteSessionEventType.REMOTE_SESSION_FAILED,
            sn=sn,
            session_id=session_id,
            session_type=session_type,
            tenant_id=tenant_id,
            terminal_id=terminal_id,
            device_id=device_id,
            lifecycle_state=RemoteSessionLifecycleState.FAILED,
            reason=reason,
            operation_id=operation_id,
            correlation_id=correlation_id,
            occurred_at=occurred_at,
            payload=payload,
        )

    async def record_console_command_started(
        self,
        session: AsyncSession,
        *,
        sn: str,
        command_id: str,
        session_id: str | None = None,
        tenant_id: int | None = None,
        terminal_id: str | None = None,
        device_id: int | None = None,
        operation_id: str | None = None,
        correlation_id: str | None = None,
        occurred_at: datetime | None = None,
        payload: dict[str, Any] | None = None,
    ) -> RemoteSessionEvent:
        cmd_payload = dict(payload or {})
        cmd_payload["command_id"] = command_id
        return await self.record_event(
            session,
            event_type=RemoteSessionEventType.CONSOLE_COMMAND_STARTED,
            sn=sn,
            session_id=session_id,
            session_type="console",
            tenant_id=tenant_id,
            terminal_id=terminal_id,
            device_id=device_id,
            lifecycle_state="executing",
            operation_id=operation_id,
            correlation_id=correlation_id,
            occurred_at=occurred_at,
            payload=cmd_payload,
        )

    async def record_console_command_completed(
        self,
        session: AsyncSession,
        *,
        sn: str,
        command_id: str,
        exit_code: int = 0,
        session_id: str | None = None,
        tenant_id: int | None = None,
        terminal_id: str | None = None,
        device_id: int | None = None,
        operation_id: str | None = None,
        correlation_id: str | None = None,
        occurred_at: datetime | None = None,
        payload: dict[str, Any] | None = None,
    ) -> RemoteSessionEvent:
        cmd_payload = dict(payload or {})
        cmd_payload["command_id"] = command_id
        cmd_payload["exit_code"] = exit_code
        return await self.record_event(
            session,
            event_type=RemoteSessionEventType.CONSOLE_COMMAND_COMPLETED,
            sn=sn,
            session_id=session_id,
            session_type="console",
            tenant_id=tenant_id,
            terminal_id=terminal_id,
            device_id=device_id,
            lifecycle_state="completed",
            reason=f"exit_code_{exit_code}",
            operation_id=operation_id,
            correlation_id=correlation_id,
            occurred_at=occurred_at,
            payload=cmd_payload,
        )

    async def record_console_command_timed_out(
        self,
        session: AsyncSession,
        *,
        sn: str,
        command_id: str,
        session_id: str | None = None,
        tenant_id: int | None = None,
        terminal_id: str | None = None,
        device_id: int | None = None,
        operation_id: str | None = None,
        correlation_id: str | None = None,
        occurred_at: datetime | None = None,
        payload: dict[str, Any] | None = None,
    ) -> RemoteSessionEvent:
        cmd_payload = dict(payload or {})
        cmd_payload["command_id"] = command_id
        cmd_payload["timeout"] = True
        return await self.record_event(
            session,
            event_type=RemoteSessionEventType.CONSOLE_COMMAND_TIMED_OUT,
            sn=sn,
            session_id=session_id,
            session_type="console",
            tenant_id=tenant_id,
            terminal_id=terminal_id,
            device_id=device_id,
            lifecycle_state="timed_out",
            reason="timeout",
            operation_id=operation_id,
            correlation_id=correlation_id,
            occurred_at=occurred_at,
            payload=cmd_payload,
        )

    # ── Durable Session Facts Management ─────────────────────────────────────────

    async def create_session(
        self,
        session: AsyncSession,
        data: RemoteSessionCreate,
    ) -> RemoteSession:
        """Create a new durable remote session with idempotency on operation_id."""
        # Check idempotency on operation_id
        existing = await session.scalar(
            select(RemoteSession).where(RemoteSession.operation_id == data.operation_id)
        )
        if existing is not None:
            log.info(
                "Idempotent create_session hit for operation_id=%s session_id=%s",
                data.operation_id,
                existing.session_id,
            )
            return existing

        res_tenant_id, res_device_id = await self.resolve_device_and_tenant(
            session, sn=data.sn, tenant_id=data.tenant_id
        )
        final_tenant_id = res_tenant_id if res_tenant_id is not None else data.tenant_id
        session_uid = f"sess-{data.session_type.value}-{uuid4().hex[:12]}"

        new_session = RemoteSession(
            session_id=session_uid,
            tenant_id=final_tenant_id,
            terminal_id=data.terminal_id,
            device_id=res_device_id,
            sn=data.sn,
            session_type=data.session_type.value,
            status=RemoteSessionLifecycleState.REQUESTED.value,
            requested_by_user_id=data.requested_by_user_id,
            operation_id=data.operation_id,
            correlation_id=data.correlation_id,
            session_metadata=data.session_metadata,
        )
        session.add(new_session)
        await session.flush()

        # Emit start_requested event
        await self.record_session_start_requested(
            session,
            session_id=session_uid,
            sn=data.sn,
            session_type=data.session_type.value,
            tenant_id=final_tenant_id,
            terminal_id=data.terminal_id,
            device_id=res_device_id,
            requested_by_user_id=data.requested_by_user_id,
            operation_id=data.operation_id,
            correlation_id=data.correlation_id,
            payload=data.session_metadata,
        )

        return new_session

    async def get_session(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> RemoteSession | None:
        return await session.scalar(
            select(RemoteSession).where(RemoteSession.session_id == session_id)
        )

    async def stop_session(
        self,
        session: AsyncSession,
        session_id: str,
        data: RemoteSessionStop,
    ) -> RemoteSession | None:
        """Stop an active or requested session idempotently."""
        rec = await self.get_session(session, session_id)
        if rec is None:
            return None

        if rec.status in (RemoteSessionLifecycleState.CLOSED.value, RemoteSessionLifecycleState.STOPPING.value):
            log.info("Session %s already in %s status", session_id, rec.status)
            return rec

        rec.status = RemoteSessionLifecycleState.CLOSED.value
        rec.closed_at = datetime.now(UTC)
        rec.close_reason = data.reason
        await session.flush()

        # Emit stop_requested and closed events
        await self.record_session_stop_requested(
            session,
            session_id=rec.session_id,
            sn=rec.sn,
            session_type=rec.session_type,
            tenant_id=rec.tenant_id,
            terminal_id=rec.terminal_id,
            device_id=rec.device_id,
            reason=data.reason,
            operation_id=data.operation_id,
            correlation_id=data.correlation_id,
        )
        await self.record_session_closed(
            session,
            session_id=rec.session_id,
            sn=rec.sn,
            session_type=rec.session_type,
            tenant_id=rec.tenant_id,
            terminal_id=rec.terminal_id,
            device_id=rec.device_id,
            reason=data.reason,
            operation_id=data.operation_id,
            correlation_id=data.correlation_id,
        )

        return rec

    async def mark_session_active(
        self,
        session: AsyncSession,
        session_id: str,
        *,
        operation_id: str | None = None,
        correlation_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> RemoteSession | None:
        rec = await self.get_session(session, session_id)
        if rec is None:
            return None

        if rec.status == RemoteSessionLifecycleState.ACTIVE.value:
            return rec

        rec.status = RemoteSessionLifecycleState.ACTIVE.value
        rec.started_at = datetime.now(UTC)
        rec.last_heartbeat_at = datetime.now(UTC)
        await session.flush()

        await self.record_session_active(
            session,
            session_id=rec.session_id,
            sn=rec.sn,
            session_type=rec.session_type,
            tenant_id=rec.tenant_id,
            terminal_id=rec.terminal_id,
            device_id=rec.device_id,
            operation_id=operation_id or rec.operation_id,
            correlation_id=correlation_id or rec.correlation_id,
            payload=payload,
        )
        return rec

    async def mark_session_failed(
        self,
        session: AsyncSession,
        session_id: str,
        reason: str = "failed",
        *,
        operation_id: str | None = None,
        correlation_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> RemoteSession | None:
        rec = await self.get_session(session, session_id)
        if rec is None:
            return None

        rec.status = RemoteSessionLifecycleState.FAILED.value
        rec.closed_at = datetime.now(UTC)
        rec.close_reason = reason
        await session.flush()

        await self.record_session_failed(
            session,
            session_id=rec.session_id,
            sn=rec.sn,
            session_type=rec.session_type,
            tenant_id=rec.tenant_id,
            terminal_id=rec.terminal_id,
            device_id=rec.device_id,
            reason=reason,
            operation_id=operation_id or rec.operation_id,
            correlation_id=correlation_id or rec.correlation_id,
            payload=payload,
        )
        return rec

    # ── Event Feed Pagination Query ──────────────────────────────────────────────

    async def get_event_feed(
        self,
        session: AsyncSession,
        *,
        after: int = 0,
        limit: int = 100,
        tenant_id: int | None = None,
        sn: str | None = None,
        session_id: str | None = None,
        event_type: str | None = None,
    ) -> RemoteSessionEventFeedResponse:
        """Query event feed with monotonic cursor pagination and deterministic ordering."""
        if after < 0:
            raise ValueError("Parameter 'after' must be a non-negative integer")
        if limit < 1 or limit > 1000:
            raise ValueError("Parameter 'limit' must be between 1 and 1000")

        stmt = (
            select(RemoteSessionEvent)
            .where(RemoteSessionEvent.cursor > after)
            .order_by(RemoteSessionEvent.cursor.asc())
        )

        if tenant_id is not None:
            stmt = stmt.where(RemoteSessionEvent.tenant_id == tenant_id)
        if sn is not None:
            stmt = stmt.where(RemoteSessionEvent.sn == sn)
        if session_id is not None:
            stmt = stmt.where(RemoteSessionEvent.session_id == session_id)
        if event_type is not None:
            stmt = stmt.where(RemoteSessionEvent.event_type == event_type)

        # Fetch limit + 1 to check if there are more pages
        stmt = stmt.limit(limit + 1)
        rows = list((await session.scalars(stmt)).all())

        has_more = len(rows) > limit
        items_page = rows[:limit]
        items_models = [RemoteSessionEventItem.model_validate(r) for r in items_page]

        next_cursor = items_page[-1].cursor if items_page else after

        return RemoteSessionEventFeedResponse(
            items=items_models,
            next_cursor=next_cursor,
            has_more=has_more,
            total_count=len(items_models),
            server_time=datetime.now(UTC),
        )

    # ── Reconciliation Query & Checksum ──────────────────────────────────────────

    async def get_reconciliation_summary(
        self,
        session: AsyncSession,
        *,
        tenant_id: int | None = None,
        from_cursor: int | None = None,
        to_cursor: int | None = None,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
    ) -> RemoteSessionReconciliationResponse:
        """Aggregate event counts, bounds, and SHA-256 digest of feed facts for reconciliation."""
        # 1. Base filter conditions
        conditions = []
        if tenant_id is not None:
            conditions.append(RemoteSessionEvent.tenant_id == tenant_id)
        if from_cursor is not None:
            conditions.append(RemoteSessionEvent.cursor >= from_cursor)
        if to_cursor is not None:
            conditions.append(RemoteSessionEvent.cursor <= to_cursor)
        if from_time is not None:
            conditions.append(RemoteSessionEvent.occurred_at >= from_time)
        if to_time is not None:
            conditions.append(RemoteSessionEvent.occurred_at <= to_time)

        # 2. Aggregates query
        agg_stmt = select(
            func.count(RemoteSessionEvent.cursor),
            func.min(RemoteSessionEvent.cursor),
            func.max(RemoteSessionEvent.cursor),
        )
        if conditions:
            agg_stmt = agg_stmt.where(sa.and_(*conditions))

        agg_res = (await session.execute(agg_stmt)).first()
        total_events = agg_res[0] if agg_res and agg_res[0] is not None else 0
        min_cursor = agg_res[1] if agg_res else None
        max_cursor = agg_res[2] if agg_res else None

        # 3. Group by event_type
        type_stmt = select(
            RemoteSessionEvent.event_type,
            func.count(RemoteSessionEvent.cursor),
        )
        if conditions:
            type_stmt = type_stmt.where(sa.and_(*conditions))
        type_stmt = type_stmt.group_by(RemoteSessionEvent.event_type)

        type_res = (await session.execute(type_stmt)).all()
        events_by_type = {row[0]: row[1] for row in type_res}

        # 4. Sessions state aggregation
        sess_conditions = []
        if tenant_id is not None:
            sess_conditions.append(RemoteSession.tenant_id == tenant_id)

        sess_status_stmt = select(
            RemoteSession.status,
            func.count(RemoteSession.id),
        )
        if sess_conditions:
            sess_status_stmt = sess_status_stmt.where(sa.and_(*sess_conditions))
        sess_status_stmt = sess_status_stmt.group_by(RemoteSession.status)
        sess_status_res = (await session.execute(sess_status_stmt)).all()
        sessions_by_status = {row[0]: row[1] for row in sess_status_res}

        active_count = sum(
            count
            for status, count in sessions_by_status.items()
            if status in (RemoteSessionLifecycleState.ACTIVE.value, RemoteSessionLifecycleState.REQUESTED.value)
        )

        # 5. Deterministic feed SHA-256 computation over ordered events in window
        hash_stmt = select(
            RemoteSessionEvent.cursor,
            RemoteSessionEvent.event_id,
            RemoteSessionEvent.event_type,
            RemoteSessionEvent.occurred_at,
        )
        if conditions:
            hash_stmt = hash_stmt.where(sa.and_(*conditions))
        hash_stmt = hash_stmt.order_by(RemoteSessionEvent.cursor.asc()).limit(5000)

        hash_rows = (await session.execute(hash_stmt)).all()
        hasher = hashlib.sha256()
        for c, eid, etype, occ in hash_rows:
            occ_str = occ.isoformat() if hasattr(occ, "isoformat") else str(occ)
            chunk = f"{c}:{eid}:{etype}:{occ_str};"
            hasher.update(chunk.encode("utf-8"))

        feed_digest = hasher.hexdigest()

        return RemoteSessionReconciliationResponse(
            tenant_id=tenant_id,
            from_cursor=from_cursor,
            to_cursor=to_cursor,
            total_events=total_events,
            min_cursor=min_cursor,
            max_cursor=max_cursor,
            events_by_type=events_by_type,
            active_sessions_count=active_count,
            sessions_by_status=sessions_by_status,
            feed_sha256=feed_digest,
            server_time=datetime.now(UTC),
        )


remote_session_event_service = RemoteSessionEventService()


async def safe_record_device_online(
    sn: str,
    *,
    tenant_id: int | None = None,
    terminal_id: str | None = None,
    device_id: int | None = None,
    correlation_id: str | None = None,
) -> None:
    """Safely record device_online in background without disrupting message transport."""
    try:
        async with db_helper.session_factory() as session:
            async with session.begin():
                await remote_session_event_service.record_device_online(
                    session,
                    sn=sn,
                    tenant_id=tenant_id,
                    terminal_id=terminal_id,
                    device_id=device_id,
                    correlation_id=correlation_id,
                )
    except Exception as exc:
        log.warning("Failed to record background device_online event for sn=%s: %s", sn, exc)
