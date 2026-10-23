"""Exercise deployed Python paths against the accepted camera vectors and secrets."""

import base64
import copy
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from core.camera import admission
from core.camera.contract import PACKAGE, REVISION, bounded_json, validate_rpc
from core.camera.media import (
    CameraEpoch,
    CameraMediaAdapter,
    CodecEvidence,
    resolve_codec,
)
from core.camera.producer import start_command, stop_command, renew_command
from core.camera.task_route import CameraTaskRoute
from core.config import settings
from core.remote_input.leases import Lease
from core.rpc_redaction import redact_rpc
from core.schemas.device_tasks import TaskCreate

FIXTURES = [
    json.loads(p.read_text()) for p in sorted((PACKAGE / "fixtures").glob("*.json"))
]
RPC_FIXTURES = [f for f in FIXTURES if f["target"] == "rpc"]


def create_task(method=160, payload=None, **extra):
    return TaskCreate(
        ext_task_id="external-id",
        device_id=4623,
        method_code=method,
        ttl=1,
        payload=payload or {"dt": [{}]},
        camera_contract_revision=REVISION,
        **extra,
    )


def snapshot():
    local = next(
        f["payload"] for f in FIXTURES if f["name"] == "local_offline_snapshot"
    )
    camera = {
        k: copy.deepcopy(v)
        for k, v in local.items()
        if k not in ("v", "hardware_id", "contract_revision", "snapshot_id")
    }
    camera["camera_contract_revision"] = REVISION
    return {
        "200": 84,
        "300": [
            {
                "450": {
                    "schema_version": 1,
                    "snapshot_id": local["snapshot_id"],
                    "cameras": [camera],
                }
            }
        ],
    }


@pytest.mark.parametrize("fixture", RPC_FIXTURES, ids=lambda f: f["name"])
def test_accepted_rpc_vectors_use_production_task_validation(fixture):
    method = int(fixture["definition"][3:])
    if fixture["valid"]:
        parsed = create_task(method, copy.deepcopy(fixture["payload"]))
        assert parsed.payload["dt"][0]["timeout_ms"] <= (
            15000 if method == 164 else 30000
        )
    else:
        with pytest.raises(ValidationError):
            create_task(method, fixture["payload"])


def test_negotiated_defaults_and_legacy_are_separate():
    assert create_task().payload["dt"][0]["timeout_ms"] == 20000
    assert "camera_contract_revision" not in create_task().model_dump()
    old = TaskCreate(
        ext_task_id="old", device_id=4623, method_code=160, payload={"dt": [{}]}
    )
    assert old.payload["dt"][0]["timeout_ms"] == 5000
    with pytest.raises(ValidationError):
        TaskCreate(
            ext_task_id="old", device_id=4623, method_code=165, payload={"dt": [{}]}
        )
    with pytest.raises(ValidationError):
        create_task(160, {"dt": [{"timeout_ms": 20000.0}]})


def sealed_payload():
    operation = str(uuid4())
    return {
        "dt": [
            {
                "action": "set_credentials",
                "expected_revision": "a" * 64,
                "operation_id": operation,
                "sealed_credentials": {
                    "v": 1,
                    "alg": "RSA-OAEP-256+A256GCM",
                    "sn": "synthetic-sn",
                    "operation_id": operation,
                    "recipient_cert_sha256": "b" * 64,
                    "expires_at_ms": int(datetime.now(UTC).timestamp() * 1000) + 45000,
                    "wrapped_key": base64.b64encode(bytes(256)).decode(),
                    "nonce": base64.b64encode(bytes(12)).decode(),
                    "ciphertext": base64.b64encode(b"synthetic-ciphertext").decode(),
                    "tag": base64.b64encode(bytes(16)).decode(),
                },
            }
        ]
    }


def test_sealed_envelope_is_opaque_and_whole_envelope_is_redacted():
    payload = sealed_payload()
    envelope = copy.deepcopy(payload["dt"][0]["sealed_credentials"])
    task = create_task(166, payload)
    assert task.payload["dt"][0]["sealed_credentials"] == envelope
    assert redact_rpc(task.payload)["dt"][0]["sealed_credentials"] == "***"
    assert task.payload["dt"][0]["sealed_credentials"] == envelope
    payload["dt"][0]["sealed_credentials"]["operation_id"] = str(uuid4())
    with pytest.raises(ValidationError):
        create_task(166, payload)


@pytest.mark.parametrize(
    "field,value",
    [("nonce", "A" * 15 + "="), ("wrapped_key", "A" * 344), ("tag", "A" * 23 + "=")],
)
def test_noncanonical_or_wrong_length_crypto_rejected(field, value):
    payload = sealed_payload()
    payload["dt"][0]["sealed_credentials"][field] = value
    with pytest.raises(ValidationError):
        create_task(166, payload)


def test_bounds_count_utf8_bytes_and_limit_depth():
    with pytest.raises(ValueError):
        bounded_json({"a": "я" * 4096}, 8192)
    value = {}
    for _ in range(14):
        value = {"nested": value}
    with pytest.raises(ValueError):
        bounded_json(value, 8192)
    with pytest.raises(ValueError):
        bounded_json({"number": float("nan")}, 8192)


def test_http_errors_and_duplicates_do_not_reflect_secrets():
    app = FastAPI()
    router = APIRouter(route_class=CameraTaskRoute)
    calls = []

    @router.post("/tasks")
    async def endpoint(task: TaskCreate):
        calls.append(task)
        return {"ok": True}

    app.include_router(router)
    with TestClient(app) as client:
        payload = sealed_payload()
        payload["dt"][0]["credentials"] = {"password": "synthetic-private-marker"}
        response = client.post(
            "/tasks",
            json={
                "ext_task_id": "test",
                "device_id": 4623,
                "method_code": 166,
                "camera_contract_revision": REVISION,
                "payload": payload,
            },
        )
        assert response.status_code == 422
        assert "synthetic-private-marker" not in response.text
        response = client.post(
            "/tasks",
            content='{"method_code":160,"payload":{"dt":[{"timeout_ms":1000,"timeout_ms":2000}]}}',
        )
        assert response.status_code == 422 and not calls


def test_gauge_reader_preserves_observed_unverified_and_rejects_secrets():
    value = snapshot()
    assert admission.validate_gauge(value) == value
    camera = admission.camera_from_gauge(value, "cam:ip000001")
    assert camera["capabilities"]["illumination"]["white"] == "unverified"
    camera["sealed_credentials"] = sealed_payload()["dt"][0]["sealed_credentials"]
    with pytest.raises(ValueError):
        admission.validate_gauge(value)


@pytest.mark.anyio
async def test_camera_gauge_persisted_separately_from_res(monkeypatch):
    from core.services import device_events_collect as collector

    lookup, gauge = AsyncMock(return_value=4623), AsyncMock()
    monkeypatch.setattr(collector.DeviceRepo, "get_device_id", lookup)
    monkeypatch.setattr(collector.DeviceRepo, "upsert_gauge", gauge)
    message = SimpleNamespace(
        headers={"event_type_code": 84}, body=json.dumps(snapshot()).encode()
    )
    await collector.DeviceEventsCollect(object(), "synthetic-sn", 1).add(message)
    assert gauge.await_args.kwargs["gauges"] == snapshot()
    bad = snapshot()
    bad["password"] = "synthetic-private-marker"
    message.body = json.dumps(bad).encode()
    await collector.DeviceEventsCollect(object(), "synthetic-sn", 1).add(message)
    assert gauge.await_count == 1


@pytest.mark.anyio
async def test_main_app_and_fresh_capability_required(monkeypatch):
    task = create_task()
    gauge = SimpleNamespace(gauges=snapshot(), updated_at=datetime.now(UTC))
    connection = SimpleNamespace(app_connect=True, is_blocked=False)
    session = SimpleNamespace(scalar=AsyncMock(side_effect=[connection, gauge]))
    await admission.admit_task(session, task, "synthetic-sn")
    connection.app_connect = False
    with pytest.raises(HTTPException, match="camera_main_app_offline"):
        await admission.admit_task(
            SimpleNamespace(scalar=AsyncMock(return_value=connection)),
            task,
            "synthetic-sn",
        )
    connection.app_connect = True
    gauge.updated_at -= timedelta(seconds=61)
    with pytest.raises(HTTPException, match="camera_capabilities_stale"):
        await admission.admit_task(
            SimpleNamespace(scalar=AsyncMock(side_effect=[connection, gauge])),
            task,
            "synthetic-sn",
        )


def test_physical_illumination_stays_denied_even_with_writer_gate(monkeypatch):
    monkeypatch.setattr(settings.camera, "writers_enabled", True)
    camera = admission.camera_from_gauge(snapshot(), "cam:ip000001")
    payload = next(
        f["payload"] for f in RPC_FIXTURES if f["name"] == "bounded_led_probe"
    )
    item = validate_rpc(167, payload)["dt"][0]
    camera["revision"] = item["expected_revision"]
    with pytest.raises(HTTPException, match="camera_physical_illumination_unverified"):
        admission.require_camera_operation(167, item, camera)


def evidence(now):
    return {
        name: CodecEvidence(now - 1000, now + 1000, "ready", "ready")
        for name in ("camera", "relay", "server", "browser")
    }


def test_camera_auto_only_falls_back_on_confirmed_unsupported():
    chain = evidence(10000)
    assert resolve_codec("auto", chain, 10000)[0] == "h265"
    chain["browser"] = CodecEvidence(9000, 11000, "ready", "unsupported")
    assert resolve_codec("auto", chain, 10000)[0] == "h264"
    with pytest.raises(ValueError):
        resolve_codec("h265", chain, 10000)
    chain["browser"] = CodecEvidence(9000, 11000, "ready", "unknown")
    with pytest.raises(ValueError):
        resolve_codec("auto", chain, 10000)
    with pytest.raises(ValueError):
        resolve_codec("auto", evidence(10000), 12000)


def epoch_and_lease():
    payload = copy.deepcopy(
        next(f["payload"] for f in FIXTURES if f["name"] == "native_hevc_level51")
    )
    lease = Lease(
        lease_id=UUID(payload["lease_id"]),
        org_id=1,
        device_id=4623,
        sn=payload["publisher"]["sn"],
        owner_user_id="operator",
        owner_role="user",
        owner_session_id="browser",
        scope="stream",
        expires_at=datetime.now(UTC) + timedelta(seconds=60),
    )
    payload["lease_expires_at"] = int(lease.expires_at.timestamp())
    return CameraEpoch.from_start(payload, lease), lease


def media_response(epoch, state="starting", health=False):
    start = epoch.start
    result = {
        key: start[key]
        for key in (
            "contract_version",
            "session_id",
            "operation_id",
            "publisher",
            "lease_id",
            "descriptor",
        )
    }
    result.update(
        stream_instance_id=start["publisher"]["stream_instance_id"],
        route_generation=1,
        state=state,
        mountpoint_id=1,
        rtp_port=10000,
        rtcp_port=10001,
        janus_ws="/janus",
    )
    if health:
        result["transport"] = {
            "connected": True,
            "rtp_packets": 10,
            "bytes": 1000,
            "last_rtp_at_ms": None,
            "rtp_fresh": False,
        }
    return result


@pytest.mark.anyio
async def test_media_roundtrip_preserves_header_descriptor_epoch_and_scoped_stop():
    epoch, lease = epoch_and_lease()
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["X-L4-Camera-Contract"] == REVISION
        assert request.headers["X-Media-Service-Token"] == "synthetic-token"
        if request.url.path.endswith("capabilities"):
            caps = copy.deepcopy(
                next(
                    f["payload"]
                    for f in FIXTURES
                    if f["name"] == "negotiated_capabilities"
                )
            )
            caps["camera_formats"][0]["runtime_verified"] = True
            return httpx.Response(200, json=caps)
        response = media_response(epoch, health=request.method == "GET")
        if request.url.path.endswith("stop"):
            body = json.loads(request.content)
            assert body["stream_instance_id"] == epoch.identity["stream_instance_id"]
            assert body["descriptor_revision"] == epoch.identity["descriptor_revision"]
            response["state"] = "stopped"
        return httpx.Response(200, json=response)

    async with httpx.AsyncClient(
        base_url="https://media.invalid", transport=httpx.MockTransport(handler)
    ) as client:
        adapter = CameraMediaAdapter(client, "synthetic-token")
        prepared, response = await adapter.prepare(epoch)
        assert response["descriptor"]["tracks"][0]["level_id"] == 153
        assert response["descriptor"]["tracks"][0]["width"] == 2592
        health = await adapter.health(prepared)
        assert health["transport"]["rtp_fresh"] is False
        assert calls[-1].url.path.endswith(epoch.identity["session_id"])
        await adapter.renew(prepared, lease)
        await adapter.stop(prepared, "user_requested")
    assert len(calls) == 5


@pytest.mark.anyio
async def test_media_mismatch_compensates_only_its_original_epoch_without_restart():
    epoch, _ = epoch_and_lease()
    calls = []

    def handler(request):
        if request.url.path.endswith("capabilities"):
            caps = copy.deepcopy(
                next(
                    f["payload"]
                    for f in FIXTURES
                    if f["name"] == "negotiated_capabilities"
                )
            )
            caps["camera_formats"][0]["runtime_verified"] = True
            return httpx.Response(200, json=caps)
        calls.append(request)
        result = media_response(epoch)
        if len(calls) == 1:
            result["stream_instance_id"] = str(uuid4())
        else:
            assert (
                json.loads(request.content)["stream_instance_id"]
                == epoch.identity["stream_instance_id"]
            )
        return httpx.Response(200, json=result)

    async with httpx.AsyncClient(
        base_url="https://media.invalid", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(ValueError):
            await CameraMediaAdapter(client, "synthetic-token").prepare(epoch)
    assert len(calls) == 2 and calls[-1].url.path.endswith("stop")


def test_actual_siplite_adapter_uses_existing_v1_identity_and_exact_track(monkeypatch):
    epoch, lease = epoch_and_lease()
    camera = admission.camera_from_gauge(snapshot(), "cam:ip000001")
    camera["actual_track"] = epoch.start["descriptor"]["tracks"][0]
    now = int(datetime.now(UTC).timestamp() * 1000)
    monkeypatch.setattr(settings.camera, "writers_enabled", True)
    cmd = start_command(epoch, camera, now)
    assert cmd.v == 1 and cmd.mode == "usb-camera" and cmd.source_id == "cam:ip000001"
    assert str(cmd.stream_instance_id) == epoch.identity["stream_instance_id"]
    assert cmd.expires_at_ms == epoch.start["lease_expires_at"] * 1000
    assert renew_command(epoch, lease, now).stream_instance_id == cmd.stream_instance_id
    assert stop_command(epoch, now).stream_instance_id == cmd.stream_instance_id
    camera["actual_track"]["level_id"] = 123
    with pytest.raises(ValueError):
        start_command(epoch, camera, now)
    assert epoch.start["descriptor"]["tracks"][0]["level_id"] == 153


class QueryResult:
    def __init__(self, value):
        self.value = value

    def one_or_none(self):
        return self.value

    def scalar_one_or_none(self):
        return self.value

    def scalar_one(self):
        return self.value


class RepositorySession:
    def __init__(self, values):
        self.values = iter(values)
        self.statements = []
        self.commit = AsyncMock()
        self.rollback = AsyncMock()

    async def execute(self, statement):
        from sqlalchemy.dialects.postgresql import dialect

        statement.compile(dialect=dialect())
        self.statements.append(statement)
        if (
            getattr(getattr(statement, "table", None), "name", "")
            == "tb_rpc_result_webhooks"
        ):
            return QueryResult(None)
        return QueryResult(next(self.values))


@pytest.mark.anyio
async def test_operation_allocates_real_task_uuid_and_replay_is_durable():
    from core.crud.dev_tasks_repo import TasksRepository

    payload = next(f["payload"] for f in RPC_FIXTURES if f["name"] == "discovery")
    task = create_task(165, payload)
    now = datetime.now(UTC).timestamp()
    session = RepositorySession([None, None, now, None, None])
    task_id, created = await TasksRepository.create_task(session, task)
    assert str(task_id) == payload["dt"][0]["operation_id"]
    assert task.ext_task_id != str(task_id)
    assert "pg_advisory_xact_lock" in str(session.statements[0])
    assert session.statements[2].compile().params["id"] == task_id
    existing = SimpleNamespace(
        device_id=task.device_id,
        method_code=task.method_code,
        is_deleted=False,
        payload=task.payload,
        initial_ttl=task.ttl,
        priority=task.priority,
        created_at=now,
    )
    replay = RepositorySession([None, existing])
    assert await TasksRepository.create_task(replay, task) == (task_id, created)
    assert len(replay.statements) == 2  # No new task/payload/deadline on reconnect.
    existing.payload = {"dt": []}
    conflict = RepositorySession([None, existing])
    with pytest.raises(HTTPException, match="camera_operation_conflict"):
        await TasksRepository.create_task(conflict, task)
    conflict.rollback.assert_awaited_once()


@pytest.mark.anyio
async def test_wrong_result_operation_is_not_committed():
    from core.crud.dev_tasks_repo import TasksRepository
    from core.models.common import TaskStatus

    task_id = uuid4()
    owner = SimpleNamespace(id=task_id, is_deleted=False, method_code=165)
    status = SimpleNamespace(
        status=TaskStatus.LOCK,
        ttl=1,
        initial_ttl=1,
        pending_at=None,
        expires_at=datetime.now(UTC) + timedelta(seconds=60),
    )
    session = RepositorySession([owner, status])
    result = await TasksRepository.record_result(
        session,
        task_id,
        "synthetic-sn",
        0,
        200,
        {"operation_id": str(uuid4()), "status": "ok"},
        None,
        datetime.now(UTC),
    )
    assert result is None
    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()
    assert len(session.statements) == 2


@pytest.mark.parametrize(
    "method,key", [(49, "password"), (49, "user"), (50, ""), (50, "*")]
)
def test_generic_nvs_cannot_bypass_private_credential_path(method, key):
    with pytest.raises(ValidationError):
        TaskCreate(
            ext_task_id="bad",
            device_id=4623,
            method_code=method,
            payload={
                "dt": [{"ns": "cfg_cam", "k": key, "v": "synthetic-private-marker"}]
            },
        )
    safe = TaskCreate(
        ext_task_id="safe",
        device_id=4623,
        method_code=49,
        payload={"dt": [{"ns": "cfg_eth", "k": "mode", "v": 0}]},
    )
    assert safe.payload["dt"][0]["v"] == 0
    assert (
        redact_rpc({"ns": "cfg_cam", "k": "password", "v": "synthetic-private-marker"})[
            "v"
        ]
        == "***"
    )


@pytest.fixture
async def camera_env(monkeypatch):
    from core.camera import control
    from core.remote_input.leases import LeaseRegistry
    from core.remote_input.presence import PresenceRegistry
    from core.remote_input.pending import PendingCommandRegistry, PendingResult
    from core.remote_input.service import RemoteInputService
    from core.remote_input.video_control import video_control

    service = RemoteInputService(
        leases=LeaseRegistry(),
        presence=PresenceRegistry(),
        pending=PendingCommandRegistry(),
    )
    lease = await service.leases.acquire(
        org_id=1,
        device_id=4623,
        sn="cam-" + uuid4().hex[:12],
        owner_user_id="operator",
        owner_role="user",
        owner_session_id="browser",
        scope="stream",
        ttl_sec=60,
    )
    prototype, _ = epoch_and_lease()
    payload = prototype.start
    payload.update(
        lease_id=str(lease.lease_id), lease_expires_at=int(lease.expires_at.timestamp())
    )
    payload["publisher"]["sn"] = lease.sn
    epoch = CameraEpoch.from_start(payload, lease)
    camera = admission.camera_from_gauge(snapshot(), "cam:ip000001")
    camera["actual_track"] = epoch.start["descriptor"]["tracks"][0]
    monkeypatch.setattr(settings.camera, "writers_enabled", True)
    monkeypatch.setattr(
        control,
        "camera_capability",
        AsyncMock(
            return_value=SimpleNamespace(
                producer_adapter={"ready": True}, camera=camera
            )
        ),
    )

    async def dispatch(sn, command, **kwargs):
        if command.type == "stream_start":
            await service.pending.resolve(
                command.command_id,
                PendingResult(
                    result="started",
                    stream_instance_id=command.stream_instance_id,
                    state="running",
                ),
                lease_id=command.lease_id,
            )

    send = AsyncMock(side_effect=dispatch)
    yield service, lease, epoch, send
    keys = await video_control.store.client.keys(
        video_control.store.key(lease.sn) + "*"
    )
    if keys:
        await video_control.store.client.delete(*keys)


@pytest.mark.anyio
async def test_camera_control_start_replay_stop_and_separate_ack_evidence(camera_env):
    from core.camera.control import camera_control, CameraStateView
    from core.remote_input.schemas import CtlStreamEvent

    service, lease, epoch, send = camera_env
    first = await camera_control.start(service, None, lease, epoch.start, send)
    assert first["confirmation"] == "command_ack"
    assert CameraStateView.from_record(first).actual_descriptor is None
    await camera_control.start(service, None, lease, epoch.start, send)
    assert send.await_count == 1
    wrong = {**epoch.identity, "stream_instance_id": str(uuid4()), "reason": "stop"}
    with pytest.raises(HTTPException, match="camera_epoch_mismatch"):
        await camera_control.stop(service, lease, wrong, send)
    record = await camera_control.stop(
        service, lease, {**epoch.identity, "reason": "stop"}, send
    )
    assert record["state"] == "stopping"  # Broker publication is not completion.
    await camera_control.event(
        lease.sn,
        CtlStreamEvent(
            sn=lease.sn,
            stream_instance_id=UUID(epoch.identity["stream_instance_id"]),
            state="stopped",
            timestamp=datetime.now(UTC).isoformat(),
        ),
        service,
    )
    assert (await camera_control.record(lease.sn))["state"] == "stopped"
    assert lease.stream_instance_id is None


@pytest.mark.anyio
async def test_camera_late_event_a_does_not_retire_b(camera_env):
    from core.camera.control import camera_control
    from core.remote_input.schemas import CtlStreamEvent

    service, lease, epoch_a, send = camera_env
    await camera_control.start(service, None, lease, epoch_a.start, send)
    stopped = CtlStreamEvent(
        sn=lease.sn,
        stream_instance_id=UUID(epoch_a.identity["stream_instance_id"]),
        state="stopped",
        timestamp=datetime.now(UTC).isoformat(),
    )
    assert await camera_control.event(lease.sn, stopped, service)
    next_start = epoch_a.start
    next_start.update(session_id=str(uuid4()), operation_id=str(uuid4()))
    next_start["publisher"]["stream_instance_id"] = str(uuid4())
    epoch_b = CameraEpoch.from_start(next_start, lease)
    await camera_control.start(service, None, lease, epoch_b.start, send)
    assert not await camera_control.event(lease.sn, stopped, service)
    assert (await camera_control.record(lease.sn))["start"] == epoch_b.start
    assert lease.stream_instance_id == UUID(epoch_b.identity["stream_instance_id"])


@pytest.mark.anyio
async def test_camera_cleanup_expiry_is_scoped_and_idempotent(camera_env):
    from core.camera.control import camera_control

    service, lease, epoch, send = camera_env
    await camera_control.start(service, None, lease, epoch.start, send)
    lease.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await camera_control.cleanup(service, send)
    await camera_control.cleanup(service, send)
    assert send.await_count == 2
    stop = send.await_args.args[1]
    assert (
        stop.type == "stream_stop"
        and str(stop.stream_instance_id) == epoch.identity["stream_instance_id"]
    )
    assert (await camera_control.record(lease.sn))["reason"] == "lease_invalid"


@pytest.mark.anyio
async def test_camera_http_negotiation_authorization_and_state(camera_env, monkeypatch):
    from api.internal_v1 import remote_input as api
    from core.camera.control import camera_control

    service, lease, epoch, send = camera_env
    monkeypatch.setattr(api, "remote_input_service", service)
    monkeypatch.setattr(settings.auth, "internal_service_key", "synthetic-service-key")
    monkeypatch.setattr(api, "send_ctl_command", send)

    class SessionContext:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(api.db_helper, "session_factory", lambda: SessionContext())
    app = FastAPI()
    app.include_router(api.router)
    headers = {
        "X-Internal-Service-Key": "synthetic-service-key",
        "X-Org-Id": "1",
        "X-User-Id": "operator",
        "X-Session-Id": "browser",
        "X-Role": "user",
        "X-L4-Camera-Contract": REVISION,
    }
    base = f"/remote-input/lease/{lease.lease_id}"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", headers=headers
    ) as client:
        bad = await client.post(
            base + "/stream/start", json=epoch.start, headers={"X-Org-Id": "2"}
        )
        assert bad.status_code == 403
        response = await client.post(base + "/stream/start", json=epoch.start)
        assert response.status_code == 200, response.text
        assert response.json()["camera_contract_revision"] == REVISION
        assert response.json()["descriptor"] == epoch.start["descriptor"]
        state = await client.get(base + "/video-state")
        assert state.status_code == 200
        client.headers.pop("X-L4-Camera-Contract")
        assert (await client.get(base + "/video-state")).status_code == 422
        assert (
            await client.post(base + "/stream/start", json=epoch.start)
        ).status_code == 422
    assert (await camera_control.record(lease.sn))["confirmation"] == "command_ack"


@pytest.mark.anyio
async def test_camera_cleanup_watches_lease_renew_race(camera_env, monkeypatch):
    from core.camera.control import camera_control
    from core.remote_input.video_control import video_control
    from core.remote_input.leases import RedisLeaseRegistry, _lease_to_dict

    service, lease, epoch, send = camera_env
    await camera_control.start(service, None, lease, epoch.start, send)
    service.leases = RedisLeaseRegistry()
    client = video_control.store.client
    await client.hset(f"l4d:lease:{lease.lease_id}", mapping=_lease_to_dict(lease))
    await client.set(f"l4d:lease:active:{lease.sn}", str(lease.lease_id))
    await client.hset(
        f"l4d:lease:{lease.lease_id}", "expires_at", "2020-01-01T00:00:00+00:00"
    )
    original = video_control.publisher_lease
    raced = False

    async def renew(service, candidate, pipe):
        nonlocal raced
        result = await original(service, candidate, pipe)
        if not raced:
            raced = True
            await client.hset(
                f"l4d:lease:{lease.lease_id}",
                "expires_at",
                lease.expires_at.isoformat(),
            )
        return result

    monkeypatch.setattr(video_control, "publisher_lease", renew)
    assert not await camera_control.reconcile(lease.sn, service, send)
    assert raced and send.await_count == 1
    assert (await camera_control.record(lease.sn))["state"] == "running"
    await client.delete(f"l4d:lease:{lease.lease_id}", f"l4d:lease:active:{lease.sn}")


@pytest.mark.anyio
async def test_camera_duplicate_snapshot_preserves_database_freshness():
    from core.crud.device_repo import DeviceRepo
    from sqlalchemy.dialects.postgresql import dialect

    session = RepositorySession([123])
    assert await DeviceRepo.upsert_gauge(session, 1, 4623, "84", snapshot()) == 123
    sql = str(session.statements[0].compile(dialect=dialect()))
    assert "CASE WHEN" in sql and "updated_at = CASE" in sql
    assert (
        "excluded.gauges" in sql
        and "snapshot_id" in session.statements[0].compile().params.values()
    )


def test_mutations_reach_production_validator_at_every_rpc_object():
    count = 0
    for fixture in RPC_FIXTURES:
        if not fixture["valid"]:
            continue

        def paths(value, path=()):
            if isinstance(value, dict):
                yield path
                for key, child in value.items():
                    yield from paths(child, (*path, key))
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    yield from paths(child, (*path, index))

        for path in paths(fixture["payload"]):
            mutated = copy.deepcopy(fixture["payload"])
            node = mutated
            for key in path:
                node = node[key]
            node["__unexpected__"] = True
            with pytest.raises(ValidationError):
                create_task(int(fixture["definition"][3:]), mutated)
            count += 1
    assert count >= 20


def test_selected_codec_does_not_depend_on_unused_codec_probe():
    chain = evidence(10000)
    chain["browser"] = CodecEvidence(9000, 11000, "unknown", "ready")
    assert resolve_codec("auto", chain, 10000)[0] == "h265"
    chain["browser"] = CodecEvidence(9000, 11000, "ready", "unknown")
    assert resolve_codec("h264", chain, 10000)[0] == "h264"


def test_unverified_server_format_never_authorizes_camera_start():
    from core.camera.media import require_server_format

    epoch, _ = epoch_and_lease()
    caps = next(
        f["payload"] for f in FIXTURES if f["name"] == "negotiated_capabilities"
    )
    with pytest.raises(ValueError, match="camera_server_format_unavailable"):
        require_server_format(caps, epoch.start["descriptor"])


@pytest.mark.anyio
async def test_replay_receipt_returns_before_current_capability_or_secret_expiry(
    monkeypatch,
):
    from core.services import device_tasks
    from core.crud.dev_tasks_repo import TasksRepository

    payload = sealed_payload()
    task = create_task(166, payload)
    operation = UUID(payload["dt"][0]["operation_id"])
    monkeypatch.setattr(
        device_tasks.DeviceRepo, "get_device_sn", AsyncMock(return_value="synthetic-sn")
    )
    monkeypatch.setattr(
        TasksRepository, "camera_receipt", AsyncMock(return_value=(operation, 12345))
    )
    create = AsyncMock()
    publish = AsyncMock()
    monkeypatch.setattr(TasksRepository, "create_task", create)
    monkeypatch.setattr(device_tasks, "send_tsk", publish)
    result = await device_tasks.DeviceTasksService(object(), 1).create(task)
    assert result.id == operation and result.created_at == 12345
    create.assert_not_awaited()
    publish.assert_not_awaited()


@pytest.mark.anyio
async def test_camera_ack_after_lease_expiry_cannot_report_running(camera_env):
    from core.camera.control import camera_control
    from core.remote_input.pending import PendingResult

    service, lease, epoch, send = camera_env

    async def expire_before_ack(sn, command, **kwargs):
        if command.type == "stream_start":
            lease.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await service.pending.resolve(
                command.command_id,
                PendingResult(
                    result="started",
                    stream_instance_id=command.stream_instance_id,
                    state="running",
                ),
                lease_id=lease.lease_id,
            )

    send.side_effect = expire_before_ack
    with pytest.raises(ValueError):
        await camera_control.start(service, None, lease, epoch.start, send)
    assert (await camera_control.record(lease.sn))["state"] == "failed"
    assert send.await_count == 2
    assert send.await_args.args[1].type == "stream_stop"
