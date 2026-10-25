"""Real runtime paths: fencing, durable replay protection and monotonic budgets."""

import asyncio
import copy
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from core.camera.runtime import CameraRuntime
from core.camera.runtime_state import initial_state
from core.camera.runtime_wire import (
    ADMISSION,
    ENROLLMENT,
    MAX_COUNTER,
    decode,
    digest,
    validate,
)
from core.config import settings

SN = "runtime-fixture"
BOOT = "00000000-0000-4000-8000-000000000001"
ROOT = Path(__file__).resolve().parents[4]


class Clock:
    def __init__(self):
        self.tick = 100000
        self.wall = 1800000000000
        self.db = datetime(2026, 10, 24, tzinfo=UTC)

    def advance(self, milliseconds):
        self.tick += milliseconds
        self.db += timedelta(milliseconds=milliseconds)


class DurableStore:
    """Transactional shared store with JSONB-style key reordering and rollback."""

    def __init__(self, clock):
        self.clock = clock
        self.row = SimpleNamespace(state=initial_state(), owner=None, owner_until=None)
        self.lock = asyncio.Lock()

    @asynccontextmanager
    async def locked(self, sn):
        assert sn == SN
        async with self.lock:
            before = copy.deepcopy(self.row)
            try:
                yield self.row, self.clock.db
                self.row.state = json.loads(json.dumps(self.row.state, sort_keys=True))
            except BaseException:
                self.row = before
                raise

    async def get(self, sn):
        assert sn == SN
        return copy.deepcopy(self.row.state)


def descriptor():
    return json.loads(
        (
            ROOT / "contracts/siplite-camera-v1/fixtures/native_hevc_level51.json"
        ).read_text()
    )["payload"]["descriptor"]


def configured():
    d = descriptor()
    return {
        "descriptor": d,
        "binding": {
            "source_id": d["source_id"],
            "physical_camera_mac": "02:00:00:00:00:01",
            "path_generation": "port2/1/1",
            "codec": "h265",
            "descriptor_sha256": digest(d),
        },
    }


def hello(boot=BOOT, high_water=41):
    return {
        "revision": ENROLLMENT,
        "type": "camera_enrollment_hello",
        "sn": SN,
        "boot_id": boot,
        "enrollment_id": str(uuid4()),
        "admission_high_water": high_water,
        "supported_ctl": [ADMISSION],
    }


@pytest.fixture
def environment(monkeypatch):
    monkeypatch.setattr(settings.camera, "monotonic_runtime_enabled", True)
    clock = Clock()
    store = DurableStore(clock)
    sent = []

    async def send(sn, value, ttl):
        assert sn == SN and ttl > 0
        validate(value)
        # No payload can be sent before it is durably present in the outbox.
        assert any(entry["message"] == value for entry in store.row.state["outbox"])
        sent.append(copy.deepcopy(value))

    async def authority(sn, value):
        assert sn == SN
        return 60000

    runtime = CameraRuntime(
        store, send, authority, lambda: clock.tick, lambda: clock.wall
    )
    return SimpleNamespace(
        clock=clock,
        store=store,
        runtime=runtime,
        sent=sent,
        send=send,
        authority=authority,
    )


async def enroll(env, message=None):
    runtime = env.runtime
    if env.store.row.state["configured"] is None:
        await runtime.submit(SN, "configure", configured())
    h = message or hello()
    assert await runtime.submit(SN, "incoming", decode(h, SN, h["enrollment_id"]))
    offer = copy.deepcopy(env.sent[-1])
    proof = {
        **offer,
        "type": "camera_enrollment_proof",
        "admission_high_water": h["admission_high_water"],
    }
    assert await runtime.submit(
        SN, "incoming", decode(proof, SN, proof["enrollment_id"])
    )
    return h, offer, proof, copy.deepcopy(env.sent[-1])


async def ready(env):
    query = await env.runtime.submit(SN, "readiness", {"sn": SN})
    response = {
        k: v for k, v in query.items() if k not in ("issued_at_ms", "expires_at_ms")
    }
    response.update(type="camera_readiness_result", status="ready")
    assert await env.runtime.submit(
        SN, "incoming", decode(response, SN, query["readiness_nonce"])
    )
    return query, response


def start_value(query):
    return {
        "sn": SN,
        "command_id": str(uuid4()),
        "lease_id": str(uuid4()),
        "stream_instance_id": str(uuid4()),
        "descriptor_sha256": digest(descriptor()),
        "readiness_nonce": query["readiness_nonce"],
    }


async def start(env):
    query, _ = await ready(env)
    value = start_value(query)
    command = await env.runtime.submit(SN, "start", value)
    await env.runtime.submit(SN, "release", {"command_id": command["command_id"]})
    return value, command


@pytest.mark.anyio
async def test_enrollment_readiness_start_renew_stop_new_attempt(environment):
    e = environment
    _, offer, _, commit = await enroll(e)
    assert commit["admission_floor"] >= offer["admission_floor"] == 41
    value, first = await start(e)
    assert first["admission_seq"] == 42 and first["command_seq"] == 1
    assert first["expires_at_ms"] - first["issued_at_ms"] == 60000
    anchor = first["issued_at_ms"]
    for _ in range(4):
        e.clock.advance(30000)
        renew = await e.runtime.submit(SN, "renew", value)
        await e.runtime.submit(SN, "release", {"command_id": renew["command_id"]})
        assert renew["admission_seq"] == first["admission_seq"]
        assert renew["issuer_epoch"] == first["issuer_epoch"]
    assert renew["expires_at_ms"] - anchor == 180000  # offset is not capped at60s
    stop = await e.runtime.submit(SN, "stop", value)
    await e.runtime.submit(SN, "release", {"command_id": stop["command_id"]})
    assert stop["command_seq"] == 6
    _, second = await start(e)
    assert second["admission_seq"] == 43
    with pytest.raises(ValueError, match="stream_not_live"):
        await e.runtime.submit(SN, "renew", value)


@pytest.mark.anyio
async def test_duplicate_and_expired_enrollment_do_not_extend_original_budget(
    environment,
):
    e = environment
    await e.runtime.submit(SN, "configure", configured())
    h = hello()
    assert await e.runtime.submit(SN, "incoming", h)
    offer = copy.deepcopy(e.sent[-1])
    deadline = e.store.row.state["pending"]["deadline"]
    e.clock.advance(4999)
    assert await e.runtime.submit(SN, "incoming", h)
    assert e.sent[-1] == offer and e.store.row.state["pending"]["deadline"] == deadline
    e.clock.advance(1)
    proof = {**offer, "type": "camera_enrollment_proof", "admission_high_water": 41}
    assert not await e.runtime.submit(SN, "incoming", proof)
    assert not await e.runtime.submit(SN, "incoming", h)
    assert e.store.row.state["boot"] is None


@pytest.mark.anyio
async def test_wrong_proof_preserves_exchange_then_correct_floor(environment):
    e = environment
    await e.runtime.submit(SN, "configure", configured())
    e.store.row.state["boot"], e.store.row.state["counter"] = BOOT, 100
    h = hello(high_water=41)
    assert await e.runtime.submit(SN, "incoming", h)
    offer = e.sent[-1]
    assert offer["admission_floor"] == 100
    proof = {**offer, "type": "camera_enrollment_proof", "admission_high_water": 120}
    original = copy.deepcopy(e.store.row.state["pending"])
    assert not await e.runtime.submit(SN, "incoming", {**proof, "admission_floor": 42})
    assert e.store.row.state["pending"] == original
    assert await e.runtime.submit(SN, "incoming", proof)
    assert e.sent[-1]["admission_floor"] == 120


@pytest.mark.anyio
async def test_boot_retired_only_on_proof_and_cannot_return(environment):
    e = environment
    old, _, _, _ = await enroll(e)
    value, _ = await start(e)
    new = hello(str(uuid4()), 0)
    assert await e.runtime.submit(SN, "incoming", new)
    assert (
        e.store.row.state["boot"] == BOOT and BOOT not in e.store.row.state["retired"]
    )
    assert e.store.row.state["active"]  # unproved hello does not retire the live boot
    proof = {**e.sent[-1], "type": "camera_enrollment_proof", "admission_high_water": 0}
    assert await e.runtime.submit(SN, "incoming", proof)
    assert BOOT in e.store.row.state["retired"] and e.store.row.state["counter"] == 0
    assert not await e.runtime.submit(SN, "incoming", old)
    with pytest.raises(ValueError, match="stream_not_live"):
        await e.runtime.submit(SN, "renew", value)


@pytest.mark.anyio
async def test_restart_fences_old_owner_pending_and_preserves_counter(environment):
    e = environment
    _, _, old_proof, _ = await enroll(e)
    await start(e)
    old_owner = e.runtime
    before = await e.store.get(SN)
    e.clock.advance(10001)
    newer = CameraRuntime(
        e.store, e.send, e.authority, lambda: e.clock.tick, lambda: e.clock.wall
    )
    e.runtime = newer
    await newer.pump(SN)
    state = await e.store.get(SN)
    assert state["generation"] == before["generation"] + 1
    assert state["counter"] == before["counter"] and not state["enrolled"]
    assert state["active"] is None and state["epoch"] != before["epoch"]
    count = len(e.sent)
    await old_owner.flush(SN)
    assert len(e.sent) == count
    assert not await newer.submit(SN, "incoming", old_proof)
    _, _, _, commit = await enroll(e, hello(high_water=41))
    assert commit["admission_floor"] == before["counter"]
    _, command = await start(e)
    assert command["admission_seq"] == before["counter"] + 1


@pytest.mark.anyio
@pytest.mark.parametrize("delay,accepted", [(4999, True), (5000, False), (6000, False)])
async def test_readiness_pending_boundary(environment, delay, accepted):
    e = environment
    await enroll(e)
    query = await e.runtime.submit(SN, "readiness", {"sn": SN})
    response = {
        k: v for k, v in query.items() if k not in ("issued_at_ms", "expires_at_ms")
    }
    response.update(type="camera_readiness_result", status="ready")
    e.clock.advance(delay)
    assert await e.runtime.submit(SN, "incoming", response) is accepted


@pytest.mark.anyio
async def test_consumed_or_wrong_readiness_never_restarts(environment):
    e = environment
    await enroll(e)
    query, response = await ready(e)
    wrong = start_value(query)
    wrong["readiness_nonce"] = str(uuid4())
    with pytest.raises(ValueError, match="readiness_mismatch"):
        await e.runtime.submit(SN, "start", wrong)
    good = start_value(query)
    await e.runtime.submit(SN, "start", good)
    assert not await e.runtime.submit(SN, "incoming", response)
    with pytest.raises(ValueError, match="fresh_readiness_required"):
        await e.runtime.submit(SN, "start", good)


@pytest.mark.anyio
async def test_renew_at_expiry_never_revives(environment):
    e = environment
    await enroll(e)
    value, _ = await start(e)
    e.clock.advance(60000)
    with pytest.raises(ValueError, match="stream_not_live"):
        await e.runtime.submit(SN, "renew", value)
    _, new = await start(e)
    assert new["admission_seq"] == 43


@pytest.mark.anyio
async def test_held_start_and_outbox_retry_are_identical(environment):
    e = environment
    await enroll(e)
    query, _ = await ready(e)
    command = await e.runtime.submit(SN, "start", start_value(query))
    count = len(e.sent)
    await e.runtime.pump(SN)
    assert len(e.sent) == count
    attempts = []

    async def fail_once(sn, message, ttl):
        attempts.append(copy.deepcopy(message))
        if len(attempts) == 1:
            raise OSError("ambiguous broker result")
        await e.send(sn, message, ttl)

    e.runtime.send = fail_once
    await e.runtime.submit(SN, "release", {"command_id": command["command_id"]})
    assert e.store.row.state["outbox"]
    await e.runtime.pump(SN)
    assert attempts == [command, command]
    assert e.store.row.state["outbox"] == []


@pytest.mark.anyio
async def test_wall_clock_jumps_do_not_move_issuer_time(environment):
    e = environment
    await enroll(e)
    value, command = await start(e)
    e.clock.advance(30000)
    e.clock.wall -= 604800000
    renew = await e.runtime.submit(SN, "renew", value)
    assert renew["issued_at_ms"] == command["issued_at_ms"] + 30000
    assert renew["expires_at_ms"] == renew["issued_at_ms"] + 60000


@pytest.mark.anyio
async def test_stale_negative_ack_does_not_kill_new_attempt(environment):
    e = environment
    await enroll(e)
    old, command = await start(e)
    await e.runtime.submit(SN, "stop", old)
    _, new = await start(e)
    ack = {
        k: command[k] for k in ("command_id", "sn", "lease_id", "stream_instance_id")
    }
    ack.update(result="nack")
    assert await e.runtime.accept_ack(SN, ack)
    assert e.store.row.state["active"]["start"] == new


@pytest.mark.anyio
async def test_concurrent_start_consumes_single_token(environment):
    e = environment
    await enroll(e)
    query, _ = await ready(e)
    results = await asyncio.gather(
        *(e.runtime.submit(SN, "start", start_value(query)) for _ in range(8)),
        return_exceptions=True,
    )
    assert sum(isinstance(result, dict) for result in results) == 1
    assert e.store.row.state["counter"] == 42


@pytest.mark.anyio
async def test_actual_ack_received_in_other_worker_is_durable(environment):
    e = environment
    await enroll(e)
    _, command = await start(e)
    ack = {
        k: command[k] for k in ("command_id", "sn", "lease_id", "stream_instance_id")
    }
    ack.update(result="started")
    other = CameraRuntime(
        e.store, e.send, e.authority, lambda: e.clock.tick, lambda: e.clock.wall
    )
    task = asyncio.create_task(other.accept_ack(SN, ack))
    for _ in range(5):
        await asyncio.sleep(0.01)
        await e.runtime.pump(SN)
    assert await task
    from core.camera.runtime_wire import CameraRuntimeCommand

    result = await other.wait_ack(CameraRuntimeCommand(command), 0.1)
    assert result.result == "started"


def test_runtime_digest_matches_cross_language_vectors():
    data = json.loads(
        (
            ROOT / "contracts/camera-ctl-monotonic-v1/descriptor-hash-vectors.json"
        ).read_text()
    )
    for vector in data["valid"]:
        assert digest(json.loads(vector["input_json"])) == vector["sha256"]


@pytest.mark.parametrize(
    "field",
    [
        "sn",
        "boot_id",
        "enrollment_id",
        "issuer_epoch",
        "binding_hash",
        "admission_floor",
    ],
)
@pytest.mark.anyio
async def test_proof_exact_correlation(environment, field):
    e = environment
    await e.runtime.submit(SN, "configure", configured())
    assert await e.runtime.submit(SN, "incoming", hello())
    proof = {
        **e.sent[-1],
        "type": "camera_enrollment_proof",
        "admission_high_water": 41,
    }
    different = (
        100
        if field == "admission_floor"
        else (
            "b" * 64
            if field == "binding_hash"
            else "other" if field == "sn" else str(uuid4())
        )
    )
    bad = {**proof, field: different}
    if field == "sn":
        with pytest.raises(ValueError, match="sn_mismatch"):
            await e.runtime.submit(SN, "incoming", bad)
    else:
        assert not await e.runtime.submit(SN, "incoming", bad)
    assert await e.runtime.submit(SN, "incoming", proof)


@pytest.mark.parametrize(
    "transform",
    [
        lambda m: {**m, "extra": 1},
        lambda m: {**m, "admission_high_water": True},
        lambda m: {**m, "revision": "unknown"},
    ],
)
def test_strict_inbound_wire(transform):
    h = hello()
    with pytest.raises(ValueError):
        decode(transform(h), SN, h["enrollment_id"])


def test_inbound_rejects_duplicate_keys_and_wrong_correlation():
    h = hello()
    with pytest.raises(ValueError):
        decode(json.dumps(h)[:-1] + ',"sn":"other"}', SN, h["enrollment_id"])
    with pytest.raises(ValueError):
        decode(h, SN, str(uuid4()))


@pytest.mark.anyio
async def test_counter_overflow_fails_closed(environment):
    e = environment
    await enroll(e)
    e.store.row.state["counter"] = MAX_COUNTER
    with pytest.raises(ValueError, match="counter_exhausted"):
        await e.runtime.submit(SN, "readiness", {"sn": SN})
    assert e.store.row.state["counter"] == MAX_COUNTER


@pytest.mark.anyio
async def test_database_cache_key_order_does_not_evict_new_command(environment):
    e = environment
    await enroll(e)
    value, _ = await start(e)
    for _ in range(80):
        e.clock.advance(30000)
        renew = await e.runtime.submit(SN, "renew", value)
        await e.runtime.submit(SN, "release", {"command_id": renew["command_id"]})
        assert renew["command_id"] in e.store.row.state["commands"]
    assert len(e.store.row.state["commands"]) == 64
    assert len(e.store.row.state["results"]) == 64


@pytest.mark.anyio
async def test_server_monotonic_regression_invalidates_epoch_not_counter(environment):
    e = environment
    await enroll(e)
    await start(e)
    old = await e.store.get(SN)
    e.clock.tick -= 1
    await e.runtime.pump(SN)
    assert not e.store.row.state["enrolled"] and not e.store.row.state["active"]
    await e.runtime.pump(SN)
    assert e.store.row.state["epoch"] != old["epoch"]
    assert e.store.row.state["counter"] == old["counter"]


@pytest.mark.anyio
async def test_stop_cancels_unsent_start(environment):
    e = environment
    await enroll(e)
    query, _ = await ready(e)
    value = start_value(query)
    command = await e.runtime.submit(SN, "start", value)
    stop = await e.runtime.submit(SN, "stop", value)
    await e.runtime.submit(SN, "release", {"command_id": command["command_id"]})
    assert not any(msg["type"] == "stream_start" for msg in e.sent)
    await e.runtime.submit(SN, "release", {"command_id": stop["command_id"]})
    assert e.sent[-1]["type"] == "stream_stop"


@pytest.mark.anyio
async def test_old_boot_ack_is_rejected_after_new_boot_enrollment(environment):
    e = environment
    await enroll(e)
    _, command = await start(e)
    await enroll(e, hello(str(uuid4()), 0))
    ack = {
        k: command[k] for k in ("command_id", "sn", "lease_id", "stream_instance_id")
    }
    ack["result"] = "nack"
    assert not await e.runtime.accept_ack(SN, ack)


def test_authorized_configuration_requires_real_port2_observation():
    from core.camera.runtime_admission import configuration

    camera = {
        "camera_id": "cam:ip000001",
        "camera_contract_revision": "siplite-camera/1.0.0",
        "actual_track": descriptor()["tracks"][0],
        "discovery": {
            "state": "ready",
            "generation": 1,
            "physical_port": 2,
            "candidates": [
                {"mac": "02:00:00:00:00:01", "port_verified": True, "auth": "verified"}
            ],
        },
    }
    assert configuration(camera, descriptor(), "02:00:00:00:00:01") == configured()
    camera["discovery"]["candidates"][0]["port_verified"] = False
    with pytest.raises(ValueError, match="binding_unverified"):
        configuration(camera, descriptor(), "02:00:00:00:00:01")


@pytest.mark.anyio
async def test_mqtt_dispatch_checks_native_correlation(environment, monkeypatch):
    from core.camera import runtime as module
    from core.remote_input.mqtt_bridge import handle_device_ctl_message

    e = environment
    await e.runtime.submit(SN, "configure", configured())
    monkeypatch.setattr(module, "camera_runtime", e.runtime)
    h = hello()
    kwargs = {"routing_key": f"dev.{SN}.ctl", "payload": h}
    assert not await handle_device_ctl_message(**kwargs, correlation_id=str(uuid4()))
    assert await handle_device_ctl_message(**kwargs, correlation_id=h["enrollment_id"])
    assert e.sent[-1]["type"] == "camera_enrollment_offer"


def test_runtime_http_negotiation_is_explicit_and_default_off(monkeypatch):
    from api.internal_v1.remote_input import require_camera_runtime_headers
    from fastapi import HTTPException
    from starlette.requests import Request

    def request(headers):
        return Request(
            {
                "type": "http",
                "headers": [
                    (k.lower().encode(), v.encode()) for k, v in headers.items()
                ],
            }
        )

    assert not require_camera_runtime_headers(request({}), optional=True)
    with pytest.raises(HTTPException) as exc:
        require_camera_runtime_headers(request({"X-L4-Camera-Admission": ADMISSION}))
    assert exc.value.status_code == 422
    monkeypatch.setattr(settings.camera, "monotonic_runtime_enabled", False)
    with pytest.raises(HTTPException) as exc:
        require_camera_runtime_headers(
            request(
                {
                    "X-L4-Camera-Admission": ADMISSION,
                    "X-L4-Camera-Enrollment": ENROLLMENT,
                }
            )
        )
    assert exc.value.status_code == 409


@pytest.mark.anyio
async def test_short_expired_lease_allows_immediately_new_readiness(environment):
    e = environment
    await enroll(e)

    async def short_lease(sn, value):
        return 1000

    e.runtime.authority = short_lease
    await start(e)
    e.clock.advance(1000)
    new, _ = await ready(e)
    assert new["admission_seq"] == 43


@pytest.mark.anyio
async def test_redis_lease_budget_uses_active_ttl_not_wallclock_or_hash_retention(
    environment, monkeypatch
):
    from unittest.mock import AsyncMock

    from core.redis_helper import redis_helper
    from core.remote_input.leases import lease_registry

    lease_id, stream_id = uuid4(), uuid4()
    lease = SimpleNamespace(
        sn=SN, scope="stream", stream_instance_id=stream_id, is_active=lambda: True
    )
    monkeypatch.setattr(lease_registry, "get", AsyncMock(return_value=lease))
    client = redis_helper.get_client()
    await client.set(f"l4d:lease:active:{SN}", str(lease_id), px=1700)
    value = {"lease_id": str(lease_id), "stream_instance_id": str(stream_id)}
    budget = await CameraRuntime.check_lease(SN, value)
    assert 0 < budget <= 1700
    await client.delete(f"l4d:lease:active:{SN}")
    with pytest.raises(ValueError, match="lease_invalid"):
        await CameraRuntime.check_lease(SN, value)


@pytest.mark.anyio
async def test_start_publication_rechecks_revocation(environment):
    e = environment
    await enroll(e)
    query, _ = await ready(e)
    command = await e.runtime.submit(SN, "start", start_value(query))

    async def revoked(sn, value):
        raise ValueError("camera_lease_invalid")

    e.runtime.authority = revoked
    await e.runtime.submit(SN, "release", {"command_id": command["command_id"]})
    assert not any(message["type"] == "stream_start" for message in e.sent)


@pytest.mark.anyio
async def test_new_runtime_http_endpoints_preserve_org_authorization(
    environment, monkeypatch
):
    from unittest.mock import AsyncMock

    import httpx
    from api.internal_v1 import remote_input as api
    from fastapi import FastAPI

    monkeypatch.setattr(settings.auth, "internal_service_key", "runtime-test-key")
    # The auth check must reject before attempting to read a gauge or durable row.
    monkeypatch.setattr(api.DeviceRepo, "get_device_id", AsyncMock(return_value=None))
    from core.models import db_helper

    async def session():
        yield None

    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[db_helper.session_getter] = session
    headers = {
        "X-Internal-Service-Key": "runtime-test-key",
        "X-Org-Id": "1",
        "X-L4-Camera-Admission": ADMISSION,
        "X-L4-Camera-Enrollment": ENROLLMENT,
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            f"/remote-input/devices/{SN}/camera/admission", headers=headers
        )
        assert response.status_code == 403
        assert (
            await client.get(f"/remote-input/devices/{SN}/camera/admission")
        ).status_code in (401, 403)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "native_bundle",
    [False, True, "media3-low", "media3-default", "media4-low", "media4-default"],
)
async def test_actual_camera_control_uses_negotiated_outbox_and_cross_worker_ack(
    environment, monkeypatch, native_bundle
):
    from unittest.mock import AsyncMock

    from core.camera import control
    from core.camera import runtime as runtime_module
    from core.camera.media import CameraEpoch
    from core.remote_input.leases import LeaseRegistry
    from core.remote_input.pending import PendingCommandRegistry
    from core.remote_input.presence import PresenceRegistry
    from core.remote_input.publisher import send_ctl_command
    from core.remote_input.service import RemoteInputService
    from core.remote_input.video_control import video_control
    from fastapi import HTTPException

    e = environment
    monkeypatch.setattr(runtime_module, "camera_runtime", e.runtime)
    monkeypatch.setattr(settings.camera, "writers_enabled", True)
    camera = {
        "camera_id": "cam:ip000001",
        "camera_contract_revision": "siplite-camera/1.0.0",
        "actual_track": descriptor()["tracks"][0],
        "discovery": {
            "state": "ready",
            "generation": 1,
            "physical_port": 2,
            "candidates": [
                {"mac": "02:00:00:00:00:01", "port_verified": True, "auth": "verified"}
            ],
        },
    }
    observation = None
    modern04 = isinstance(native_bundle, str) and native_bundle.startswith("media4-")
    if native_bundle:
        if isinstance(native_bundle, str):
            if modern04:
                from .test_camera_cadence02 import (
                    fixture,
                    configured as base_configured,
                )
            else:
                from .test_camera_media3 import fixture, configured as base_configured

            def native_configured():
                return base_configured(native_bundle.split("-", 1)[1])

        else:
            from .test_camera_native_auto11 import (
                fixture,
                configured as native_configured,
            )

        camera = fixture("physical-camera")
        observation = fixture("observation")
    monkeypatch.setattr(
        control,
        "camera_capability",
        AsyncMock(
            return_value=SimpleNamespace(
                producer_adapter={"ready": True},
                camera=camera,
                camera_observation=observation,
                main_app_online=True,
                fresh=True,
            )
        ),
    )
    from core.remote_input.leases import RedisLeaseRegistry

    service = RemoteInputService(
        leases=(
            RedisLeaseRegistry() if isinstance(native_bundle, str) else LeaseRegistry()
        ),
        presence=PresenceRegistry(),
        pending=PendingCommandRegistry(),
    )
    lease = await service.leases.acquire(
        org_id=1,
        device_id=4623,
        sn=SN,
        owner_user_id="operator",
        owner_role="user",
        owner_session_id="browser",
        scope="stream",
        ttl_sec=60,
    )
    payload = json.loads(
        (
            ROOT / "contracts/siplite-camera-v1/fixtures/native_hevc_level51.json"
        ).read_text()
    )["payload"]
    payload.update(
        lease_id=str(lease.lease_id), lease_expires_at=int(lease.expires_at.timestamp())
    )
    payload["publisher"]["sn"] = SN
    if native_bundle:
        payload["descriptor"] = native_configured()["descriptor"]
        if isinstance(native_bundle, str):
            payload["contract_version"] = 3
    media_lease = None
    if isinstance(native_bundle, str):
        from core.camera.media_clock import camera_media_clock

        monkeypatch.setattr(
            camera_media_clock, "boot", lambda: "11111111-1111-4111-8111-111111111111"
        )
        media_lease = await camera_media_clock.export(lease, initialize=True)
        payload["lease_expires_at"] = media_lease.media_lease_expires_at
    epoch = CameraEpoch.from_start(payload, lease, media_lease=media_lease)
    if native_bundle:
        await e.runtime.submit(SN, "configure", native_configured())
        message = fixture("hello")
        message["sn"] = SN
        await enroll(e, message)
    else:
        await enroll(e)
    query, _ = await ready(e)
    tasks = []

    async def send(sn, message, ttl):
        await e.send(sn, message, ttl)
        if message["type"] == "stream_start":
            ack = {
                k: message[k]
                for k in ("sn", "command_id", "lease_id", "stream_instance_id")
            }
            ack["result"] = "started"
            tasks.append(asyncio.create_task(e.runtime.accept_ack(sn, ack)))

    e.runtime.send = send
    try:
        record = await control.camera_control.start(
            service,
            None,
            lease,
            payload,
            send_ctl_command,
            monotonic=True,
            readiness_nonce=query["readiness_nonce"],
            **({"selected": native_configured()["selection"]} if modern04 else {}),
        )
        assert record["state"] == "running" and record["confirmation"] == "command_ack"
        if native_bundle:
            view = control.CameraStateView.from_record(record)
            assert view.camera_contract_revision == (
                "siplite-camera/1.3.0"
                if modern04
                else (
                    "siplite-camera/1.2.0"
                    if isinstance(native_bundle, str)
                    else "siplite-camera/1.1.0"
                )
            )
            if isinstance(native_bundle, str):
                assert view.contract_version == 3 and view.actual_descriptor is None
            assert view.cadence_revision == (
                "camera-cadence/0.2.0-proposed"
                if modern04
                else "camera-cadence/0.1.0-proposed"
            )
            assert view.descriptor == payload["descriptor"]
        assert record["admission_revision"] == ADMISSION
        assert not service.pending._pending
        native = next(m for m in e.sent if m["type"] == "stream_start")
        assert (
            native["readiness_nonce"] == query["readiness_nonce"]
            and native["admission_seq"] == 42
        )
        with pytest.raises(
            HTTPException,
            match=(
                "incomplete_revision_bundle"
                if native_bundle
                else "runtime_revision_required"
            ),
        ):
            await control.camera_control.start(
                service, None, lease, payload, send_ctl_command
            )
        await control.camera_control.stop(
            service, lease, {**epoch.identity, "reason": "manual"}, send_ctl_command
        )
        assert (
            e.sent[-1]["type"] == "stream_stop"
            and e.sent[-1]["camera_admission_revision"] == ADMISSION
        )
        event = SimpleNamespace(
            sn=SN,
            stream_instance_id=lease.stream_instance_id,
            state="stopped",
            reason="manual",
            timestamp=datetime.now(UTC).isoformat(),
        )
        assert await control.camera_control.event(SN, event, service)
        assert not (
            await service.leases.get(lease.lease_id)
        ).is_active()  # a subsequent attempt needs a fresh lease
    finally:
        await asyncio.gather(*tasks)
        keys = await video_control.store.client.keys(video_control.store.key(SN) + "*")
        if keys:
            await video_control.store.client.delete(*keys)


@pytest.mark.anyio
async def test_outbox_does_not_repair_stale_wire_budget_with_shorter_transport_ttl(
    environment,
):
    e = environment
    await enroll(e)
    query, _ = await ready(e)
    command = await e.runtime.submit(SN, "start", start_value(query))

    async def shortened(sn, value):
        return 1000

    e.runtime.authority = shortened
    await e.runtime.submit(SN, "release", {"command_id": command["command_id"]})
    assert not any(message["type"] == "stream_start" for message in e.sent)


@pytest.mark.anyio
async def test_one_bad_authority_does_not_starve_other_actors(environment, monkeypatch):
    from unittest.mock import AsyncMock

    from core.camera import runtime as module

    async def pump(sn):
        if sn == "corrupt":
            raise ValueError("camera_authority_corrupt")

    actor = SimpleNamespace(
        owns_issuer=True,
        store=SimpleNamespace(
            candidates=AsyncMock(return_value=["corrupt", "healthy"])
        ),
        pump=AsyncMock(side_effect=pump),
    )

    async def stop(_):
        raise asyncio.CancelledError

    monkeypatch.setattr(module.asyncio, "sleep", stop)
    with pytest.raises(asyncio.CancelledError):
        await module.camera_runtime_loop(actor)
    assert [call.args[0] for call in actor.pump.await_args_list] == [
        "corrupt",
        "healthy",
    ]


@pytest.mark.anyio
async def test_web_clients_recycle_without_replacing_live_issuer(environment):
    env = environment
    await enroll(env)
    _, command = await start(env)
    original_owner = env.store.row.owner
    original_clock = copy.deepcopy(env.runtime.clocks)
    original_epoch = env.store.row.state["epoch"]
    original_active = copy.deepcopy(env.store.row.state["active"])

    # New clients represent recycled API/MQTT ingress workers. Only the separate
    # executor processes their persisted jobs; clients cannot allocate clocks.
    for _ in range(3):
        client = CameraRuntime(
            env.store,
            env.send,
            env.authority,
            lambda: env.clock.tick,
            lambda: env.clock.wall,
            owns_issuer=False,
        )
        pending = asyncio.create_task(
            client.submit(SN, "release", {"command_id": command["command_id"]})
        )
        await asyncio.sleep(0)
        assert env.store.row.state["jobs"]
        await env.runtime.pump(SN)
        assert await pending
        assert client.clocks == {} and client._owner == ""
        assert env.store.row.owner == original_owner
        assert env.store.row.state["epoch"] == original_epoch
        assert env.store.row.state["active"] == original_active
        assert env.runtime.clocks == original_clock


@pytest.mark.anyio
async def test_ingress_cannot_pump_flush_or_acquire_owner(environment):
    env = environment
    client = CameraRuntime(store=env.store, owns_issuer=False)
    before = copy.deepcopy(env.store.row)
    with pytest.raises(ValueError, match="camera_client_cannot_own_issuer"):
        _ = client.owner
    for operation in (client.pump, client.flush):
        with pytest.raises(ValueError, match="camera_client_cannot_own_issuer"):
            await operation(SN)
    assert env.store.row == before
    from core.camera.runtime import camera_runtime

    assert not camera_runtime.owns_issuer


def test_retired_boot_cannot_gain_a_case_alias():
    h = hello("AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA")
    with pytest.raises(ValueError, match="canonical_v4"):
        decode(h, SN, h["enrollment_id"])
