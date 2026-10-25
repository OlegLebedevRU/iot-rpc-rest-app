"""Exact new bundle, full firmware-computable offers and preserved authority."""

import asyncio
import copy
import hashlib
import json
import runpy
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from core.camera.authority_state import load_state
from core.camera.native_contract import (
    CAPABILITIES,
    MEDIA11,
    SELECTED,
    headers11,
    selected_headers,
    validate11,
)
from core.camera.projection import camera_capability
from core.camera.runtime import CameraRuntime
from core.camera.runtime_admission import configuration
from core.camera.runtime_state import initial_state
from core.camera.runtime_wire import canonical, decode, digest, validate
from core.config import CameraConfig, settings
from fastapi import FastAPI

ROOT = Path(__file__).resolve().parents[4]
PACKAGE = ROOT / "contracts/camera-enrollment-v0.2"


def fixture(name):
    return json.loads((PACKAGE / f"fixtures/{name}.json").read_text())


def test_owner_package_is_exactly_pinned():
    lock = json.loads((ROOT / "contracts/siplite-camera-v1.1.lock.json").read_text())
    package = ROOT / "contracts/siplite-camera-v1.1"
    assert lock["owner_commit"] == "60a2bffc961dfc31caeea96a76bfb856484212b5"
    for name, expected in lock["files"].items():
        assert hashlib.sha256((package / name).read_bytes()).hexdigest() == expected
    assert lock["canonical_vectors_sha256"] == lock["files"]["canonical-vectors.json"]


@pytest.mark.parametrize(
    "mutation", ["partial", "duplicate", "wrong_source", "unknown_policy"]
)
def test_native_gauge_requires_strict_unique_device_observation(mutation):
    from core.camera.admission import validate_gauge

    value = gauge()
    observations = value["300"][0]["450"]["media_observations"]
    if mutation == "partial":
        del observations[0]["capabilities"]["camera_admission_revisions"]
    elif mutation == "duplicate":
        observations.append(copy.deepcopy(observations[0]))
    elif mutation == "wrong_source":
        observations[0]["source_id"] = ""
    else:
        observations[0]["cadence_revision"] = "unknown"
    with pytest.raises(ValueError):
        validate_gauge(value)


class Store:
    def __init__(self):
        self.row = SimpleNamespace(state=initial_state(), owner=None, owner_until=None)
        self.lock = asyncio.Lock()
        self.now = datetime(2026, 10, 24, tzinfo=UTC)

    @asynccontextmanager
    async def locked(self, sn):
        async with self.lock:
            previous = copy.deepcopy(self.row)
            try:
                self.row.state = load_state(self.row.state)
                yield self.row, self.now
                self.row.state = load_state(
                    json.loads(json.dumps(self.row.state, sort_keys=True))
                )
            except BaseException:
                self.row = previous
                raise

    async def get(self, sn):
        return load_state(self.row.state)


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(settings.camera, "monotonic_runtime_enabled", True)
    monkeypatch.setattr(settings.camera, "native_auto_enabled", True)
    store, sent, tick = Store(), [], [100000]

    async def send(sn, message, ttl):
        validate(message)
        assert ttl > 0
        sent.append(copy.deepcopy(message))

    async def lease(sn, value):
        return 60000

    runtime = CameraRuntime(store, send, lease, lambda: tick[0], lambda: 1800000000000)
    return SimpleNamespace(
        store=store, runtime=runtime, tick=tick, sent=sent, send=send, lease=lease
    )


def configured():
    return configuration(
        fixture("physical-camera"),
        fixture("offer")["descriptor"],
        fixture("offer")["binding"]["physical_camera_mac"],
        observation=fixture("observation"),
        selection=copy.deepcopy(SELECTED),
    )


async def enrolled(env, high_water=41):
    hello = fixture("hello")
    hello.update(enrollment_id=str(uuid4()), admission_high_water=high_water)
    sn = hello["sn"]
    if env.store.row.state["configured"] is None:
        await env.runtime.submit(sn, "configure", configured())
    assert await env.runtime.submit(
        sn, "incoming", decode(hello, sn, hello["enrollment_id"])
    )
    offer = copy.deepcopy(env.sent[-1])
    proof = {
        **offer,
        "type": "camera_enrollment_proof",
        "admission_high_water": high_water,
    }
    assert await env.runtime.submit(
        sn, "incoming", decode(proof, sn, hello["enrollment_id"])
    )
    return hello, offer, proof, copy.deepcopy(env.sent[-1])


async def ready(env, sn):
    query = await env.runtime.submit(sn, "readiness", {"sn": sn})
    result = {
        k: v for k, v in query.items() if k not in ("issued_at_ms", "expires_at_ms")
    }
    result.update(type="camera_readiness_result", status="ready")
    assert await env.runtime.submit(sn, "incoming", result)
    return query


@pytest.mark.anyio
async def test_full_offer_is_computable_from_device_facts_and_new_revision(env):
    hello, offer, proof, commit = await enrolled(env)
    reference = runpy.run_path(str(PACKAGE / "verify.py"))
    device = reference["Device"](
        hello, fixture("observation"), fixture("physical-camera")
    )
    assert device.offer(offer, 10)
    assert offer["descriptor"] == configured()["descriptor"]
    assert offer["binding"]["path_generation"] == "port2/3/17"
    assert offer["binding"]["descriptor_sha256"] == digest(offer["descriptor"])
    assert offer["binding_hash"] == digest(offer["binding"])
    assert device.commit(commit, 4999)
    assert (
        proof["descriptor"]["descriptor_revision"]
        == offer["descriptor"]["descriptor_revision"]
    )


@pytest.mark.parametrize(
    "part",
    [
        "X-L4-Camera-Contract",
        "X-L4-Camera-Cadence",
        "X-L4-Camera-Enrollment",
        "X-L4-Camera-Admission",
    ],
)
def test_every_header_is_required_for_new_bundle(part):
    headers = headers11()
    del headers[part]
    with pytest.raises(ValueError, match="incomplete_revision_bundle"):
        selected_headers(headers)
    headers = headers11()
    headers[part] = "unknown"
    with pytest.raises(ValueError):
        selected_headers(headers)


@pytest.mark.parametrize(
    "field", ["camera_contract_revisions", "camera_cadence_revisions", "supported_ctl"]
)
@pytest.mark.anyio
async def test_hello_cannot_omit_new_negotiation(env, field):
    await env.runtime.submit(fixture("hello")["sn"], "configure", configured())
    message = fixture("hello")
    del message[field]
    with pytest.raises(ValueError):
        decode(message, message["sn"], message["enrollment_id"])
    assert env.store.row.state["pending"] is None


@pytest.mark.anyio
async def test_old_enrollment_cannot_negotiate_new_configuration(env):
    h = fixture("hello")
    await env.runtime.submit(h["sn"], "configure", configured())
    old = {
        k: v
        for k, v in h.items()
        if k not in ("camera_contract_revisions", "camera_cadence_revisions")
    }
    old["revision"] = "camera-enrollment/0.1.0-proposed"
    assert not await env.runtime.submit(h["sn"], "incoming", old)
    assert env.store.row.state["pending"] is None


@pytest.mark.parametrize(
    "field", ["physical_camera_mac", "path_generation", "boot_id", "codec"]
)
@pytest.mark.anyio
async def test_rehashed_binding_substitution_still_rejects_pending_proof(env, field):
    h = fixture("hello")
    await env.runtime.submit(h["sn"], "configure", configured())
    assert await env.runtime.submit(h["sn"], "incoming", h)
    proof = {
        **env.sent[-1],
        "type": "camera_enrollment_proof",
        "admission_high_water": 41,
    }
    pending = copy.deepcopy(env.store.row.state["pending"])
    bad = copy.deepcopy(proof)
    bad["binding"][field] = {
        "physical_camera_mac": "02:00:00:00:00:02",
        "path_generation": "port2/4/17",
        "boot_id": str(uuid4()),
        "codec": "h264",
    }[field]
    bad["binding_hash"] = digest(bad["binding"])
    try:
        accepted = await env.runtime.submit(h["sn"], "incoming", bad)
    except ValueError:
        accepted = False
    assert not accepted and env.store.row.state["pending"] == pending
    assert await env.runtime.submit(h["sn"], "incoming", proof)


@pytest.mark.parametrize(
    "field,value",
    [
        ("cadence_revision", "constant-policy"),
        ("geometry_generation", 18),
        ("camera_contract_revision", "siplite-camera/1.0.0"),
    ],
)
def test_descriptor_policy_or_geometry_substitution_is_not_observation(field, value):
    descriptor = fixture("offer")["descriptor"]
    descriptor[field] = value
    with pytest.raises(ValueError):
        configuration(
            fixture("physical-camera"),
            descriptor,
            fixture("offer")["binding"]["physical_camera_mac"],
            observation=fixture("observation"),
            selection=SELECTED,
        )


def test_both_markers_enter_hash_even_with_identical_track():
    d = fixture("offer")["descriptor"]
    before = digest(d)
    d["cadence_revision"] = "constant-policy"
    assert digest(d) != before
    with pytest.raises(ValueError):
        validate11("camera_descriptor", d)


def test_complete_message_byte_and_depth_boundaries():
    proof = fixture("proof")
    raw = canonical(proof).encode()
    assert len(raw) == 1614
    assert decode(raw + b" " * (4096 - len(raw)), proof["sn"], proof["enrollment_id"])
    with pytest.raises(ValueError):
        decode(raw + b" " * (4097 - len(raw)), proof["sn"], proof["enrollment_id"])
    from core.camera.contract import bounded_json

    deep = copy.deepcopy(proof)
    deep["unknown"] = [[[[[[[0]]]]]]]
    bounded_json(deep, 4096, 8)
    deep["unknown"] = [[[[[[[[0]]]]]]]]
    with pytest.raises(ValueError, match="bounds"):
        bounded_json(deep, 4096, 8)


def test_version_upgrade_preserves_every_existing_authority_value():
    old = initial_state()
    old.update(
        version=1,
        counter=100,
        generation=7,
        boot=fixture("hello")["boot_id"],
        retired=[str(uuid4())],
    )
    upgraded = load_state(old)
    assert upgraded["version"] == 2 and old["version"] == 1
    assert {k: v for k, v in upgraded.items() if k != "version"} == {
        k: v for k, v in old.items() if k != "version"
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("counter", None),
        ("counter", True),
        ("counter", -1),
        ("version", 99),
        ("retired", None),
    ],
)
def test_corrupt_authority_is_not_recreated(field, value):
    old = initial_state()
    old[field] = value
    with pytest.raises(ValueError, match="authority_corrupt"):
        load_state(old)
    old = initial_state()
    del old[field]
    with pytest.raises(ValueError, match="authority_corrupt"):
        load_state(old)


@pytest.mark.anyio
async def test_floor100_and_retired_boots_survive_new_configuration_and_takeover(env):
    h = fixture("hello")
    env.store.row.state.update(
        version=1, counter=100, boot=h["boot_id"], retired=[str(uuid4())]
    )
    retired = list(env.store.row.state["retired"])
    _, offer, _, commit = await enrolled(env)
    assert offer["admission_floor"] == commit["admission_floor"] == 100
    assert env.store.row.state["retired"] == retired
    q = await ready(env, h["sn"])
    assert q["admission_seq"] == 101
    env.tick[0] += 10001
    env.store.now += timedelta(milliseconds=10001)
    new = CameraRuntime(
        env.store, env.send, env.lease, lambda: env.tick[0], lambda: 1800000000000
    )
    await new.pump(h["sn"])
    assert (
        env.store.row.state["counter"] == 101
        and env.store.row.state["retired"] == retired
    )
    assert env.store.row.state["ready"] is None and not env.store.row.state["enrolled"]


@pytest.mark.anyio
async def test_full_offer_original_deadline_and_corrected_proof(env):
    h = fixture("hello")
    await env.runtime.submit(h["sn"], "configure", configured())
    env.store.row.state["boot"], env.store.row.state["counter"] = h["boot_id"], 100
    assert await env.runtime.submit(h["sn"], "incoming", h)
    offer = copy.deepcopy(env.sent[-1])
    proof = {**offer, "type": "camera_enrollment_proof", "admission_high_water": 41}
    assert not await env.runtime.submit(
        h["sn"], "incoming", {**proof, "admission_floor": 42}
    )
    env.tick[0] += 4999
    assert await env.runtime.submit(h["sn"], "incoming", h)
    assert env.sent[-1] == offer
    assert await env.runtime.submit(h["sn"], "incoming", proof)
    assert env.sent[-1]["admission_floor"] == 100


def gauge():
    return {
        "200": 84,
        "300": [
            {
                "450": {
                    "schema_version": 1,
                    "snapshot_id": str(uuid4()),
                    "cameras": [fixture("physical-camera")],
                    "media_observations": [fixture("observation")],
                }
            }
        ],
    }


@pytest.mark.anyio
async def test_http_projection_separates_observation_server_support_and_authority(
    monkeypatch,
):
    monkeypatch.setattr(settings.camera, "native_auto_enabled", False)
    connection = SimpleNamespace(app_connect=True, is_blocked=False)
    snapshot = SimpleNamespace(gauges=gauge(), updated_at=datetime.now(UTC))
    session = SimpleNamespace(scalar=AsyncMock(side_effect=[connection, snapshot]))
    view = await camera_capability(
        session, 4623, authorized_sn="full-offer-fixture", native=True
    )
    assert view.camera_contract_revision == MEDIA11
    assert view.camera_observation == fixture("observation")
    assert view.camera_capabilities == CAPABILITIES
    assert view.fresh and view.camera["actual_track"] is None
    assert not view.producer_adapter["ready"]
    legacy = await camera_capability(
        SimpleNamespace(scalar=AsyncMock(side_effect=[connection, snapshot])), 4623
    )
    assert (
        legacy.camera["actual_track"] is None and not legacy.producer_adapter["ready"]
    )


@pytest.mark.anyio
async def test_selected_http_projection_matches_published_owner_shape(monkeypatch):
    from api.internal_v1 import remote_input as api
    from core.models import db_helper

    monkeypatch.setattr(settings.auth, "internal_service_key", "native-bundle-test")
    monkeypatch.setattr(api.DeviceRepo, "get_device_id", AsyncMock(return_value=4623))

    async def session():
        yield SimpleNamespace(
            scalar=AsyncMock(
                side_effect=[
                    SimpleNamespace(app_connect=True, is_blocked=False),
                    SimpleNamespace(gauges=gauge(), updated_at=datetime.now(UTC)),
                ]
            )
        )

    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[db_helper.session_getter] = session
    headers = {
        **headers11(),
        "X-Internal-Service-Key": "native-bundle-test",
        "X-Org-Id": "1",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/remote-input/devices/full-offer-fixture/video-capabilities",
            headers=headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["camera_observation"] == fixture("observation")
        assert response.json()["camera_capabilities"] == CAPABILITIES
        del headers["X-L4-Camera-Cadence"]
        assert (
            await client.get(
                "/remote-input/devices/full-offer-fixture/video-capabilities",
                headers=headers,
            )
        ).status_code == 422


def test_all_new_gates_remain_default_off():
    assert not CameraConfig().native_auto_enabled
    assert not CameraConfig().monotonic_runtime_enabled


@pytest.mark.anyio
async def test_native_runtime_long_renew_replay_cache_and_scoped_stop(env):
    hello, _, proof, _ = await enrolled(env)
    sn = hello["sn"]
    query = await ready(env, sn)
    start = await env.runtime.submit(
        sn,
        "start",
        {
            "sn": sn,
            "command_id": str(uuid4()),
            "lease_id": str(uuid4()),
            "stream_instance_id": str(uuid4()),
            "descriptor_sha256": digest(configured()["descriptor"]),
            "readiness_nonce": query["readiness_nonce"],
        },
    )
    assert start["binding"]["descriptor_sha256"] == digest(
        fixture("offer")["descriptor"]
    )
    identity = {k: start[k] for k in ("sn", "lease_id", "stream_instance_id")}
    for i in range(70):
        env.tick[0] += 1000
        renewal = await env.runtime.submit(sn, "renew", identity)
        assert renewal["command_seq"] == i + 2
        assert renewal["expires_at_ms"] - renewal["issued_at_ms"] == 60000
        assert renewal["binding"] == start["binding"]
        await env.runtime.submit(sn, "release", {"command_id": renewal["command_id"]})
    assert len(env.store.row.state["commands"]) == 64
    assert start["command_id"] not in env.store.row.state["commands"]
    assert not await env.runtime.submit(sn, "incoming", proof)
    with pytest.raises(ValueError, match="stream_not_live"):
        await env.runtime.submit(
            sn, "stop", {**identity, "stream_instance_id": str(uuid4())}
        )
    stop = await env.runtime.submit(sn, "stop", identity)
    assert stop["command_seq"] == 72 and stop["binding"] == start["binding"]
    assert env.store.row.state["active"] is None
    late_result = {
        k: v for k, v in query.items() if k not in ("issued_at_ms", "expires_at_ms")
    }
    assert not await env.runtime.submit(
        sn,
        "incoming",
        {**late_result, "type": "camera_readiness_result", "status": "ready"},
    )


@pytest.mark.anyio
async def test_completed_floor_corruption_is_rejected_without_reset(env):
    await enrolled(env, high_water=100)
    before = copy.deepcopy(env.store.row.state)
    env.store.row.state["completed"]["commit"]["admission_floor"] = 42
    with pytest.raises(ValueError, match="authority_corrupt"):
        await env.store.get(fixture("hello")["sn"])
    assert env.store.row.state["counter"] == before["counter"] == 100


@pytest.mark.anyio
async def test_native_media_lifecycle_preserves_bundle_and_policy():
    from core.camera.media import CameraEpoch, CameraMediaAdapter
    from .test_camera_negotiated import FIXTURES, epoch_and_lease, media_response

    old, lease = epoch_and_lease()
    body = old.start
    body["descriptor"] = fixture("offer")["descriptor"]
    epoch = CameraEpoch.from_start(body, lease)
    calls = []

    def handler(request):
        calls.append(request)
        for key, expected in headers11().items():
            assert request.headers[key] == expected
        if request.url.path.endswith("capabilities"):
            caps = copy.deepcopy(
                next(
                    f["payload"]
                    for f in FIXTURES
                    if f["name"] == "negotiated_capabilities"
                )
            )
            caps.update(CAPABILITIES)
            caps["camera_formats"][0]["runtime_verified"] = True
            return httpx.Response(200, json=caps)
        response = media_response(epoch, health=request.method == "GET")
        if request.url.path.endswith("stop"):
            response["state"] = "stopped"
        return httpx.Response(200, json=response)

    async with httpx.AsyncClient(
        base_url="https://media.invalid", transport=httpx.MockTransport(handler)
    ) as client:
        adapter = CameraMediaAdapter(client, "synthetic-token", selection=SELECTED)
        prepared, response = await adapter.prepare(epoch)
        assert response["descriptor"] == body["descriptor"]
        await adapter.health(prepared)
        await adapter.renew(prepared, lease)
        await adapter.stop(prepared, "user_requested")
        with pytest.raises(ValueError, match="selection_mismatch"):
            await CameraMediaAdapter(client, "synthetic-token").health(prepared)
    assert len(calls) == 5
