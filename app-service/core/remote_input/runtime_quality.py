"""One runtime quality writer: the original active desktop publisher session."""

from __future__ import annotations

import hashlib
import hmac
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from core.remote_input.video_control import now_ms, video_control


class QualitySet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    v: Literal[1] = 1
    type: Literal["stream_quality_set"] = "stream_quality_set"
    sn: str
    command_id: UUID
    lease_id: UUID
    stream_instance_id: UUID
    generation: int = Field(gt=0, le=2**32 - 1)
    target_bitrate_kbps: int = Field(ge=100, le=4000)
    issued_at_ms: int
    expires_at_ms: int


class QualityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stream_instance_id: UUID
    writer_key: UUID
    target_bitrate_kbps: int = Field(ge=100, le=4000)


class QualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    v: Literal[1]
    type: Literal["stream_quality_report"]
    sn: str = Field(min_length=1, max_length=128)
    lease_id: UUID
    stream_instance_id: UUID
    agent_instance_id: UUID
    sample_seq: int = Field(gt=0)
    generation: int = Field(ge=0, le=2**32 - 1)
    applied_kbps: int = Field(ge=0, le=4000)
    status: int = Field(ge=0, le=99)
    transport_age_ms: int = Field(ge=0, le=2**32 - 1)
    delivery_kbps: int = Field(ge=0, le=2**32 - 1)
    flags: int = Field(ge=0, le=7)
    raw_replaced: int = Field(ge=0, le=2**32 - 1)


def desktop_record(doc: dict[str, Any], stream: str) -> dict[str, Any]:
    active = doc.get("stream") or {}
    start = active.get("start") or {}
    descriptor = start.get("descriptor") or {}
    if (
        active.get("state") != "running"
        or start.get("stream_instance_id") != stream
        or descriptor.get("contract_version") != 3
        or descriptor.get("source_type") != "desktop"
    ):
        raise HTTPException(409, detail={"code": "quality_stream_unavailable"})
    return start


def ceiling(start: dict[str, Any]) -> int:
    return 4000 if start["descriptor"]["profile_id"] == "default" else 2000


class RuntimeQuality:
    async def report(self, sn: str, report: QualityReport) -> bool:
        value = report.model_dump(mode="json")

        def accept(doc: dict[str, Any]) -> bool:
            try:
                start = desktop_record(doc, str(report.stream_instance_id))
            except HTTPException:
                return False
            old = doc.get("runtime_quality") or {}
            pending = doc.get("quality_pending") or {}
            max_generation = (
                pending.get("generation", 0)
                if pending.get("stream_instance_id") == str(report.stream_instance_id)
                else 0
            )
            if (
                report.sn != sn
                or str(report.lease_id) != start["lease_id"]
                or str(report.agent_instance_id) != start["agent_instance_id"]
                or report.applied_kbps > ceiling(start)
                or report.generation > max_generation
                or (
                    old.get("stream_instance_id") == str(report.stream_instance_id)
                    and old.get("sample_seq", 0) >= report.sample_seq
                )
            ):
                return False
            doc["runtime_quality"] = dict(value, received_ms=now_ms())
            return True

        return await video_control.store.change(sn, accept)

    async def reply(self, sn: str, reply: dict[str, Any]) -> bool:
        def accept(doc: dict[str, Any]) -> bool:
            pending = doc.get("quality_pending") or {}
            if (
                not pending
                or str(reply.get("command_id")) != pending["command_id"]
                or str(reply.get("lease_id")) != pending["lease_id"]
                or reply.get("sn") != sn
                or pending["expires_at_ms"] <= now_ms()
            ):
                return False
            try:
                desktop_record(doc, pending["stream_instance_id"])
            except HTTPException:
                return False
            if reply.get("stream_instance_id") not in (
                None,
                pending["stream_instance_id"],
            ):
                return False
            pending["ack"] = reply.get("result") or reply.get("type")
            pending["code"] = reply.get("code")
            return True

        return await video_control.store.change(sn, accept)

    async def get(self, sn: str, stream: str) -> dict[str, Any]:
        doc = await video_control.store.get(sn)
        try:
            start = desktop_record(doc, stream)
        except HTTPException:
            return {"available": False}
        report = doc.get("runtime_quality") or {}
        if report.get("stream_instance_id") != stream or not report.get("flags", 0) & 1:
            return {"available": False}
        age = max(0, now_ms() - report["received_ms"])
        pending = doc.get("quality_pending") or {}
        if pending.get("stream_instance_id") != stream:
            pending = {}
        status = "limited" if report["applied_kbps"] < ceiling(start) else "nominal"
        if pending.get("ack") == "nack" and pending.get("code") == "unsupported":
            status = "unsupported"
        elif pending.get("ack") in ("nack", "publish_failed"):
            status = "unconfirmed"
        elif pending.get("generation", 0) > report["generation"]:
            status = "pending" if pending["expires_at_ms"] > now_ms() else "unconfirmed"
        elif report["status"]:
            status = "unsupported"
        transport = age < 3000 and bool(report["flags"] & 4)
        return {
            "available": True,
            "ceiling_kbps": ceiling(start),
            "applied_kbps": report["applied_kbps"],
            "generation": report["generation"],
            "requested_generation": pending.get("generation", 0),
            "status": status,
            "report_age_ms": age,
            "transport_available": transport,
            "transport_age_ms": report["transport_age_ms"] if transport else None,
            "delivery_kbps": report["delivery_kbps"] if transport else None,
            "transport_pressure": bool(report["flags"] & 2) if transport else None,
            "raw_replaced": report["raw_replaced"],
        }

    async def set(
        self,
        service: Any,
        lease_id: UUID,
        org_id: int,
        user: str,
        session: str,
        body: QualityRequest,
        send: Any,
    ) -> dict[str, Any]:
        # No SU override: even an administrator/other tab is not this publisher.
        lease = await video_control.authorize(service, lease_id, org_id, user, session)
        command_id = uuid4()

        async def guard(pipe: Any, doc: dict[str, Any]) -> None:
            start = desktop_record(doc, str(body.stream_instance_id))
            if start["lease_id"] != str(lease_id):
                raise HTTPException(409, detail={"code": "lease_mismatch"})
            current = await video_control.publisher_lease(service, start, pipe)
            original = doc["stream"]
            if (
                current is None
                or current.scope not in ("stream", "input")
                or current.org_id != org_id
                or current.owner_user_id != user
                or current.owner_session_id != session
                or original.get("org_id") != org_id
                or original.get("owner_user_id") != user
                or original.get("owner_session_id") != session
                or not hmac.compare_digest(
                    original.get("quality_writer_hash", ""),
                    hashlib.sha256(str(body.writer_key).encode()).hexdigest(),
                )
            ):
                raise HTTPException(403, detail={"code": "quality_publisher_required"})

        def reserve(doc: dict[str, Any]) -> QualitySet:
            start = desktop_record(doc, str(body.stream_instance_id))
            report = doc.get("runtime_quality") or {}
            if (
                report.get("stream_instance_id") != str(body.stream_instance_id)
                or not report.get("flags", 0) & 1
            ):
                raise HTTPException(409, detail={"code": "runtime_quality_unsupported"})
            if body.target_bitrate_kbps > ceiling(start):
                raise HTTPException(
                    422, detail={"code": "quality_above_selected_profile"}
                )
            previous = doc.get("quality_pending") or {}
            generation = (
                previous.get("generation", 0) + 1
                if previous.get("stream_instance_id") == str(body.stream_instance_id)
                else 1
            )
            now = now_ms()
            command = QualitySet(
                sn=lease.sn,
                command_id=command_id,
                lease_id=lease_id,
                stream_instance_id=body.stream_instance_id,
                generation=generation,
                target_bitrate_kbps=body.target_bitrate_kbps,
                issued_at_ms=now,
                expires_at_ms=min(now + 5000, int(lease.expires_at.timestamp() * 1000)),
            )
            if command.expires_at_ms <= now:
                raise HTTPException(409, detail={"code": "lease_invalid"})
            doc["quality_pending"] = command.model_dump(mode="json")
            return command

        command = await video_control.store.change(lease.sn, reserve, guard=guard)
        try:
            await send(
                lease.sn, command, ttl_ms=command.expires_at_ms - command.issued_at_ms
            )
        except Exception:  # noqa: BLE001 - broker-specific exceptions.
            # The accepted intent is not an applied encoder setting. A fresh
            # native report remains the sole application confirmation.
            def failed(doc: dict[str, Any]) -> None:
                pending = doc.get("quality_pending") or {}
                if pending.get("command_id") == str(command_id):
                    pending["ack"] = "publish_failed"

            await video_control.store.change(lease.sn, failed)
            raise HTTPException(
                503, detail={"code": "quality_publish_failed"}
            ) from None
        return {
            "accepted": True,
            "command_id": str(command_id),
            "generation": command.generation,
        }


runtime_quality = RuntimeQuality()
