"""Unified media-v3 camera objects remain fenced by the camera control adapter."""

import copy
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from starlette.requests import Request
from pydantic import ValidationError

from core.camera.admission import validate_gauge
from core.camera.authority_state import load_state
from core.camera.control import CameraStart, CameraStateView
from core.camera.media import CameraEpoch, CameraMediaAdapter
from core.camera.media_clock import MediaLease
from core.camera.native_contract import (
    CAPABILITIES3,
    MEDIA12,
    MEDIA3,
    SELECTED3,
    headers3,
    selected_headers,
    validate3,
    validate12,
)
from core.camera.projection import camera_capability
from core.camera.runtime_admission import configuration
from core.camera.runtime_wire import decode, digest, validate
from core.config import CameraConfig, settings
from core.remote_input.video_api import selected_media_version

from .test_camera_native_auto11 import env as _shared_env
from .test_camera_negotiated import epoch_and_lease, media_response

ROOT = Path(__file__).resolve().parents[4]
PACKAGE = ROOT / "contracts/camera-enrollment-v0.3"


@pytest.fixture
def env(monkeypatch):
    return _shared_env.__wrapped__(monkeypatch)


def fixture(name):
    return json.loads((PACKAGE / f"fixtures/{name}.json").read_text())


def configured(profile="default", codec="h265"):
    descriptor = fixture("offer")["descriptor"]
    descriptor["profile_id"] = profile
    observation = fixture("observation")
    if codec == "h264":
        observation["actual_track"] = json.loads(
            (
                ROOT / "contracts/siplite-camera-v1.2/example-h264-observation.json"
            ).read_text()
        )["actual_track"]
        descriptor["tracks"] = [observation["actual_track"]]
    return configuration(
        fixture("physical-camera"),
        descriptor,
        fixture("offer")["binding"]["physical_camera_mac"],
        observation=observation,
        selection=copy.deepcopy(SELECTED3),
    )


def gauge():
    return {
        "200": 84,
        "300": [
            {
                "450": {
                    "snapshot_id": str(uuid4()),
                    "cameras": [fixture("physical-camera")],
                    "media_observations": [fixture("observation")],
                }
            }
        ],
    }


async def enrolled(e, profile="default", codec="h265"):
    hello = fixture("hello")
    hello["enrollment_id"] = str(uuid4())
    sn = hello["sn"]
    await e.runtime.submit(sn, "configure", configured(profile, codec))
    assert await e.runtime.submit(
        sn, "incoming", decode(hello, sn, hello["enrollment_id"])
    )
    offer = copy.deepcopy(e.sent[-1])
    proof = {**offer, "type": "camera_enrollment_proof", "admission_high_water": 41}
    assert await e.runtime.submit(
        sn, "incoming", decode(proof, sn, hello["enrollment_id"])
    )
    return hello, offer, proof, copy.deepcopy(e.sent[-1])


async def ready(e, sn):
    query = await e.runtime.submit(sn, "readiness", {"sn": sn})
    response = {
        k: v for k, v in query.items() if k not in ("issued_at_ms", "expires_at_ms")
    }
    response.update(type="camera_readiness_result", status="ready")
    assert await e.runtime.submit(sn, "incoming", response)
    return query


def test_frozen_media_and_owner_observation_are_byte_pinned():
    common = ROOT / "contracts/l4-media-v3/media.schema.json"
    assert (
        hashlib.sha256(common.read_bytes()).hexdigest()
        == "b86ca6f066fcdecb09cf7145a7fb23d87b77311a53c7ea04f0fb6e8a905b2818"
    )
    lock = json.loads((ROOT / "contracts/siplite-camera-v1.2.lock.json").read_text())
    for name, expected in lock["files"].items():
        assert (
            hashlib.sha256(
                (ROOT / "contracts/siplite-camera-v1.2" / name).read_bytes()
            ).hexdigest()
            == expected
        )
    validate12("camera_observation", fixture("observation"))
    validate12("camera_capabilities", CAPABILITIES3)


@pytest.mark.parametrize("profile", ["low", "default"])
@pytest.mark.parametrize("codec", ["h264", "h265"])
@pytest.mark.anyio
async def test_common_descriptor_enrollment_and_legacy_control_profile_are_distinct(
    env, profile, codec
):
    hello, offer, _, commit = await enrolled(env, profile, codec)
    descriptor = offer["descriptor"]
    validate3("descriptor", descriptor)
    assert descriptor["contract_version"] == 3 and descriptor["profile_id"] == profile
    assert (
        "camera_contract_revision" not in descriptor
        and "cadence_revision" not in descriptor
    )
    assert (
        offer["media_contract_revision"] == MEDIA3
        and offer["camera_contract_revision"] == MEDIA12
    )
    assert commit["descriptor"] == descriptor
    query = await ready(env, hello["sn"])
    start = await env.runtime.submit(
        hello["sn"],
        "start",
        {
            "sn": hello["sn"],
            "command_id": str(uuid4()),
            "lease_id": str(uuid4()),
            "stream_instance_id": str(uuid4()),
            "descriptor_sha256": digest(descriptor),
            "readiness_nonce": query["readiness_nonce"],
        },
    )
    validate(start)
    assert (
        start["v"] == 1
        and start["mode"] == "usb-camera"
        and start["profile"] == "default"
    )
    assert start["binding"]["descriptor_sha256"] == digest(descriptor)
    assert start["expires_at_ms"] - start["issued_at_ms"] == 60000
    identity = {k: start[k] for k in ("sn", "lease_id", "stream_instance_id")}
    env.tick[0] += 1000
    renewal = await env.runtime.submit(hello["sn"], "renew", identity)
    assert renewal["binding"] == start["binding"] and renewal["command_seq"] == 2
    await env.runtime.submit(hello["sn"], "stop", identity)
    assert env.store.row.state["active"] is None
    late = {
        k: v for k, v in query.items() if k not in ("issued_at_ms", "expires_at_ms")
    }
    late.update(type="camera_readiness_result", status="ready")
    assert not await env.runtime.submit(hello["sn"], "incoming", late)


@pytest.mark.parametrize("header", list(headers3()))
def test_every_camera_v3_header_is_mandatory(header):
    headers = headers3()
    assert selected_headers(headers) == SELECTED3
    del headers[header]
    with pytest.raises(ValueError):
        selected_headers(headers)


@pytest.mark.parametrize(
    "mutation", ["camera_marker", "cadence_marker", "v2", "bool", "profile"]
)
def test_common_descriptor_cannot_be_forked_or_mixed(mutation):
    descriptor = configured()["descriptor"]
    if mutation == "camera_marker":
        descriptor["camera_contract_revision"] = MEDIA12
    elif mutation == "cadence_marker":
        descriptor["cadence_revision"] = "camera-cadence/0.1.0-proposed"
    elif mutation == "v2":
        descriptor["contract_version"] = 2
    elif mutation == "bool":
        descriptor["contract_version"] = True
    else:
        descriptor["profile_id"] = "native_auto"
    with pytest.raises(ValueError):
        validate3("descriptor", descriptor)


@pytest.mark.anyio
async def test_old_enrollment_cannot_commit_v3_or_lower_durable_floor(env):
    h = fixture("hello")
    await env.runtime.submit(h["sn"], "configure", configured())
    env.store.row.state.update(boot=h["boot_id"], counter=100)
    old = copy.deepcopy(h)
    old["revision"] = "camera-enrollment/0.2.0-proposed"
    old.pop("media_contract_revisions")
    old["camera_contract_revisions"] = ["siplite-camera/1.1.0"]
    assert not await env.runtime.submit(h["sn"], "incoming", old)
    assert await env.runtime.submit(h["sn"], "incoming", h)
    offer = copy.deepcopy(env.sent[-1])
    proof = {**offer, "type": "camera_enrollment_proof", "admission_high_water": 41}
    assert not await env.runtime.submit(
        h["sn"], "incoming", {**proof, "admission_floor": 42}
    )
    env.tick[0] += 4999
    assert await env.runtime.submit(h["sn"], "incoming", proof)
    assert env.sent[-1]["admission_floor"] == env.store.row.state["counter"] == 100
    state = load_state(env.store.row.state)
    assert state["configured"]["descriptor"]["contract_version"] == 3


@pytest.mark.parametrize("age, fresh", [(0, True), (29, True), (31, False)])
@pytest.mark.anyio
async def test_v3_projection_never_promotes_observation_to_legacy_or_authority(
    monkeypatch, age, fresh
):
    monkeypatch.setattr(settings.camera, "native_auto_enabled", False)
    value = gauge()
    validate_gauge(value)
    session = SimpleNamespace(
        scalar=AsyncMock(
            side_effect=[
                SimpleNamespace(app_connect=True, is_blocked=False),
                SimpleNamespace(
                    gauges=value, updated_at=datetime.now(UTC) - timedelta(seconds=age)
                ),
            ]
        )
    )
    view = await camera_capability(
        session, 4623, authorized_sn="full-offer-fixture", native=True, media_version=3
    )
    assert view.contract_version == 3 and view.media_contract_revision == MEDIA3
    assert view.camera["actual_track"] is None and view.camera_observation == fixture(
        "observation"
    )
    assert view.fresh is fresh and not view.producer_adapter["ready"]
    assert view.camera_capabilities["quality_options"] == [
        {"profile_id": "low"},
        {"profile_id": "default"},
    ]


@pytest.mark.anyio
async def test_http_camera3_selection_preserves_desktop_and_rejects_partial_headers(
    monkeypatch,
):
    from api.internal_v1 import remote_input as api
    from core.models import db_helper

    monkeypatch.setattr(settings.auth, "internal_service_key", "camera3-fixture-key")
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
        **headers3(),
        "X-Internal-Service-Key": "camera3-fixture-key",
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
        assert response.json()["camera_capabilities"] == CAPABILITIES3
        for header in headers3():
            partial = {k: v for k, v in headers.items() if k != header}
            assert (
                await client.get(
                    "/remote-input/devices/full-offer-fixture/video-capabilities",
                    headers=partial,
                )
            ).status_code == 422
    desktop = Request(
        {"type": "http", "headers": [(b"x-l4-media-contract", MEDIA3.encode())]}
    )
    assert selected_media_version(desktop) == 3
    mixed = Request(
        {
            "type": "http",
            "headers": [
                (b"x-l4-media-contract", MEDIA3.encode()),
                (b"x-l4-camera-contract", b"siplite-camera/1.0.0"),
            ],
        }
    )
    with pytest.raises(HTTPException):
        selected_media_version(mixed)


@pytest.mark.parametrize("profile", ["low", "default"])
@pytest.mark.parametrize("codec", ["h264", "h265"])
@pytest.mark.anyio
async def test_camera_media_lifecycle_uses_only_common_media_headers(profile, codec):
    old, lease = epoch_and_lease()
    body = old.start
    body["contract_version"] = 3
    body["descriptor"] = configured(profile, codec)["descriptor"]
    media_lease = MediaLease(
        body["lease_expires_at"],
        30000,
        str(uuid4()),
        body["lease_expires_at"] * 1000 - 30000,
    )
    epoch = CameraEpoch.from_start(body, lease, media_lease=media_lease)
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["X-L4-Media-Contract"] == MEDIA3
        assert not any(k.startswith("x-l4-camera-") for k in request.headers)
        if request.url.path.endswith("capabilities"):
            return httpx.Response(
                200,
                json={
                    "contract_version": 3,
                    "media_contract_versions": [3],
                    "server_revision": "fixture3",
                    "dependencies_ready": True,
                    "hevc_runtime_verified": True,
                    "codecs": [codec],
                    "formats": [
                        {
                            "codec": codec,
                            "codec_profile": body["descriptor"]["tracks"][0][
                                "codec_profile"
                            ],
                            "packetization": body["descriptor"]["tracks"][0][
                                "packetization"
                            ],
                            "clock_rate": 90000,
                        }
                    ],
                    "max_video_tracks": 1,
                    "audio_supported": False,
                    "reverse_rtcp": False,
                },
            )
        response = media_response(epoch)
        response["contract_version"] = 3
        if request.method == "GET":
            response["transport"] = {
                "connected": True,
                "rtp_packets": 1,
                "bytes": 500,
                "last_rtp_at_ms": 1000,
                "rtp_fresh": True,
            }
        return httpx.Response(200, json=response)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://media"
    ) as client:
        adapter = CameraMediaAdapter(
            client, "fixture-service-token", selection=SELECTED3
        )
        epoch, response = await adapter.prepare(epoch, media_lease=media_lease)
        assert response["descriptor"] == configured(profile, codec)["descriptor"]
        assert epoch.identity["contract_version"] == 3
        await adapter.health(epoch)
        lease.expires_at -= timedelta(days=365)
        assert not lease.is_active()
        await adapter.renew(epoch, lease, media_lease=media_lease)
        renewal = json.loads(calls[-1].content)
        assert renewal["lease_expires_at"] == media_lease.media_lease_expires_at
        with pytest.raises(ValueError, match="clock_mismatch"):
            await adapter.renew(epoch, lease)
        await adapter.stop(epoch, "test_complete")
    state = CameraStateView.from_record(
        {
            "start": body,
            "result": "started",
            "state": "running",
            "confirmation": "command_ack",
            "media_clock_id": media_lease.media_clock_id,
        }
    )
    assert (
        state.contract_version == 3
        and state.version == 2
        and state.actual_descriptor is None
    )
    assert state.camera_contract_revision == MEDIA12


def test_quality_policy_must_be_advertised_by_actual_source():
    observation = fixture("observation")
    observation["capabilities"]["quality_options"] = [{"profile_id": "default"}]
    selected = configured("low")
    with pytest.raises(ValueError, match="quality_policy_unsupported"):
        configuration(
            fixture("physical-camera"),
            selected["descriptor"],
            selected["binding"]["physical_camera_mac"],
            observation=observation,
            selection=SELECTED3,
        )


def test_camera_enrollment_cannot_authorize_desktop_under_valid_common_descriptor():
    offer = fixture("offer")
    offer["descriptor"]["source_type"] = "desktop"
    # Shared descriptor permits desktop; the camera adapter must narrow authority.
    validate3("descriptor", offer["descriptor"])
    old, _ = epoch_and_lease()
    request = {**old.start, "contract_version": 3, "descriptor": offer["descriptor"]}
    validate3("media_start", request)
    with pytest.raises(ValidationError, match="camera_source_type_required"):
        CameraStart.model_validate(request)
    offer["binding"]["descriptor_sha256"] = digest(offer["descriptor"])
    offer["binding_hash"] = digest(offer["binding"])
    with pytest.raises(ValueError, match="camera_source_type_required"):
        validate(offer)
    with pytest.raises(ValueError, match="camera_source_type_required"):
        configuration(
            fixture("physical-camera"),
            offer["descriptor"],
            offer["binding"]["physical_camera_mac"],
            observation=fixture("observation"),
            selection=SELECTED3,
        )


@pytest.mark.anyio
async def test_readiness_http_budget_does_not_restart_after_slow_owner_submit(
    monkeypatch,
):
    from api.internal_v1 import remote_input as api
    from core.camera import runtime as runtime_module

    tick = [1000]
    query = {"readiness_nonce": str(uuid4())}
    state = {
        "configured": configured(),
        "ready": {"query": query, "accepted": True, "consumed": False},
    }

    async def submit(sn, action, value, timeout):
        assert action == "readiness" and timeout == 5
        tick[0] += 5001
        return query

    runtime = SimpleNamespace(
        monotonic=lambda: tick[0],
        submit=submit,
        store=SimpleNamespace(get=AsyncMock(return_value=state)),
    )
    monkeypatch.setattr(runtime_module, "camera_runtime", runtime)
    monkeypatch.setattr(settings.camera, "monotonic_runtime_enabled", True)
    monkeypatch.setattr(settings.camera, "native_auto_enabled", True)
    monkeypatch.setattr(
        api,
        "runtime_camera_view",
        AsyncMock(
            return_value=SimpleNamespace(
                camera=fixture("physical-camera"),
                camera_observation=fixture("observation"),
            )
        ),
    )
    request = Request(
        {
            "type": "http",
            "headers": [
                (k.lower().encode(), v.encode()) for k, v in headers3().items()
            ],
        }
    )
    with pytest.raises(HTTPException) as error:
        await api.fresh_camera_readiness("full-offer-fixture", 1, None, None, request)
    assert (
        error.value.status_code == 504
        and error.value.detail == "camera_readiness_timeout"
    )
    assert runtime.store.get.await_count == 1


def test_production_gates_remain_default_off():
    assert not CameraConfig().monotonic_runtime_enabled
    assert not CameraConfig().native_auto_enabled
