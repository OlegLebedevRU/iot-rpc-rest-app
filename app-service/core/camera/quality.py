"""Original-initiator quality intents through the existing camera issuer actor."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException

from core.camera.quality_contract import CameraQualityReport, QualityRequest, REVISION
from core.camera.runtime import camera_runtime
from core.camera.quality_policy import quality_enabled
from core.remote_input.runtime_quality import original_writer
from core.remote_input.video_control import now_ms, video_control


def running(doc: dict, stream: str) -> dict:
    record = doc.get("camera_stream") or {}
    start = record.get("start") or {}
    if (
        record.get("state") != "running"
        or (start.get("publisher") or {}).get("stream_instance_id") != stream
        or not record.get("quality_authority")
        or start.get("contract_version") != 3
    ):
        raise HTTPException(409, {"code": "quality_stream_unavailable"})
    return record


class CameraQuality:
    async def report(self, sn: str, report: CameraQualityReport) -> bool:
        def accept(doc: dict) -> bool:
            try:
                record = running(doc, str(report.stream_instance_id))
            except HTTPException:
                return False
            start, authority = record["start"], record["quality_authority"]
            old = record.get("quality_report") or {}
            pending = record.get("quality_pending") or {}
            actual = report.actual
            if (
                report.sn != sn
                or start["publisher"]["sn"] != sn
                or str(report.lease_id) != start["lease_id"]
                or any(
                    str(getattr(report, key)) != str(authority[key])
                    for key in authority
                )
                or report.generation > pending.get("generation", 0)
                or report.generation < old.get("generation", 0)
                or report.sample_seq <= old.get("sample_seq", 0)
                or (
                    actual
                    and actual.codec
                    and actual.codec != start["descriptor"]["tracks"][0]["codec"]
                )
                or (
                    report.generation == pending.get("generation")
                    and report.requested.model_dump(mode="json", exclude_none=True)
                    != pending["target"]
                )
            ):
                return False
            record["quality_report"] = dict(
                report.model_dump(mode="json", exclude_none=True), received_ms=now_ms()
            )
            if (
                actual
                and actual.applied_bitrate_kbps
                and "quality_initial_kbps" not in record
            ):
                record["quality_initial_kbps"] = actual.applied_bitrate_kbps
            return True

        return await video_control.store.change(sn, accept)

    async def get(self, sn: str, stream: str) -> dict:
        try:
            record = running(await video_control.store.get(sn), stream)
        except HTTPException:
            return {"available": False}
        report = record.get("quality_report") or {}
        if not report:
            return {"available": False}
        pending = record.get("quality_pending") or {}
        age = max(0, now_ms() - report["received_ms"])
        status = "nominal" if report["status"] == "applied" else report["status"]
        if "target_bitrate_kbps" not in report.get(
            "supported_targets", []
        ) and status not in ("pending", "unconfirmed"):
            status = "unsupported"
        if pending.get("generation", 0) > report["generation"]:
            status = (
                "pending"
                if now_ms() - pending["accepted_ms"] < 15000
                else "unconfirmed"
            )
        return {
            "available": True,
            "quality_revision": REVISION,
            "report_age_ms": max(0, now_ms() - report["received_ms"]),
            "report": report,
            "pending": record.get("quality_pending"),
            "initial_bitrate_kbps": record.get("quality_initial_kbps"),
            "ceiling_kbps": record.get("quality_initial_kbps"),
            "applied_kbps": (report.get("actual") or {}).get("applied_bitrate_kbps"),
            "generation": report["generation"],
            "requested_generation": pending.get("generation", 0),
            "status": status,
            "transport_available": age < 3000
            and report.get("transport_pressure") is not None,
            "transport_pressure": report.get("transport_pressure"),
            "bitrate_min_kbps": report.get("bitrate_min_kbps"),
            "requested_kbps": (
                pending.get("target") or report.get("requested") or {}
            ).get("target_bitrate_kbps"),
            "source_origin": report.get("origin"),
            "persistence": report.get("persistence"),
        }

    async def set(
        self,
        service: Any,
        lease_id: UUID,
        org: int,
        user: str,
        session: str,
        body: QualityRequest,
    ) -> dict:
        # The camera guard below checks the Redis/media monotonic lease. Do not
        # reintroduce desktop UTC is_active() at this authentication boundary.
        lease = await video_control.authorize(
            service, lease_id, org, user, session, require_active=False
        )
        if not quality_enabled(lease.sn):
            raise HTTPException(403, {"code": "camera_quality_disabled"})

        async def guard(pipe: Any, doc: dict) -> None:
            from core.camera.control import camera_control, epoch_of

            record = running(doc, str(body.stream_instance_id))
            epoch = epoch_of(record)
            current = await camera_control.publisher_lease(
                service, epoch.identity, pipe
            )
            if record["start"]["lease_id"] != str(lease_id):
                raise HTTPException(409, {"code": "lease_mismatch"})
            if (
                not original_writer(
                    record, current, org, user, session, body.writer_key
                )
                or current.scope != "stream"
            ):
                raise HTTPException(403, {"code": "quality_publisher_required"})

        def reserve(doc: dict) -> dict:
            record = running(doc, str(body.stream_instance_id))
            report = record.get("quality_report") or {}
            target = body.target.model_dump(mode="json", exclude_none=True)
            if set(target) - set(report.get("supported_targets", [])):
                raise HTTPException(409, {"code": "runtime_quality_unsupported"})
            generation = (record.get("quality_pending") or {}).get("generation", 0) + 1
            record["quality_pending"] = {
                "command_id": str(uuid4()),
                "generation": generation,
                "target": target,
                "accepted_ms": now_ms(),
            }
            return {
                "pending": dict(record["quality_pending"]),
                "media_clock_id": record["media_clock_id"],
            }

        reserved = await video_control.store.change(lease.sn, reserve, guard=guard)
        pending = reserved["pending"]
        try:
            await camera_runtime.submit(
                lease.sn,
                "quality",
                {
                    **pending,
                    "sn": lease.sn,
                    "lease_id": str(lease_id),
                    "stream_instance_id": str(body.stream_instance_id),
                    "owner_user_id": user,
                    "owner_session_id": session,
                    "media_clock_id": reserved["media_clock_id"],
                },
            )
        except (ValueError, TimeoutError) as exc:
            raise HTTPException(409, {"code": "camera_quality_unconfirmed"}) from exc
        return {
            "accepted": True,
            "command_id": pending["command_id"],
            "generation": pending["generation"],
        }


camera_quality = CameraQuality()
