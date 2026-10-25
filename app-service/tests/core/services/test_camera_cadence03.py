"""New cadence ownership is explicit; old enrollment cannot authorize its attempt."""

import copy
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from starlette.requests import Request

from core.camera.admission import validate_gauge
from core.camera.authority_state import load_state
from core.camera.control import CameraStateView, CameraStateView14
from core.camera.native_contract import (
    CAPABILITIES5,
    SELECTED4,
    SELECTED5,
    MEDIA14,
    CADENCE03,
    ENROLLMENT05,
    headers4,
    headers5,
    selected_headers,
    validate14,
)
from core.camera.projection import camera_capability
from core.camera.runtime_admission import configuration
from core.camera.runtime_wire import decode, digest, validate
from core.config import settings

from .test_camera_media3 import env as env, ready
from .test_camera_cadence02 import enrolled as enrolled04

ROOT = Path(__file__).resolve().parents[4]


def test_owner14_raw_lock_and_old_observation_rejection():
    packet = ROOT / "contracts/siplite-camera-v1.4"
    lock = json.loads((ROOT / "contracts/siplite-camera-v1.4.lock.json").read_text())
    assert lock["commit"] == "bbf48660a36a997f688d57fc84d5c9deeedd5bd8"
    for name, expected in lock["files"].items():
        assert hashlib.sha256((packet / name).read_bytes()).hexdigest() == expected
    for key, value in (
        ("camera_contract_revision", "siplite-camera/1.3.0"),
        ("cadence_revision", "camera-cadence/0.2.0-proposed"),
    ):
        old = fixture("observation")
        old[key] = value
        with pytest.raises(ValueError):
            validate14("camera_observation", old)


def fixture(name):
    return json.loads(
        (
            ROOT / "contracts/camera-enrollment-v0.5/fixtures" / (name + ".json")
        ).read_text()
    )


def configured(profile="default", codec="h265", fps=20):
    descriptor = fixture("offer")["descriptor"]
    descriptor["profile_id"] = profile
    observation = fixture("observation")
    if codec == "h264":
        observation["actual_track"] = json.loads(
            (
                ROOT / "contracts/siplite-camera-v1.4/example-h264-observation.json"
            ).read_text()
        )["actual_track"]
    observation["actual_track"]["fps"] = fps
    descriptor["tracks"] = [observation["actual_track"]]
    return configuration(
        fixture("physical-camera"),
        descriptor,
        fixture("offer")["binding"]["physical_camera_mac"],
        observation=observation,
        selection=copy.deepcopy(SELECTED5),
    )


def gauge(fps=20):
    value = configured(fps=fps)
    return {
        "200": 84,
        "300": [
            {
                "450": {
                    "snapshot_id": str(uuid4()),
                    "cameras": [fixture("physical-camera")],
                    "media_observations": [value["observation"]],
                }
            }
        ],
    }


async def enrolled(e, profile="default", codec="h265", fps=20):
    hello = fixture("hello")
    hello["enrollment_id"] = str(uuid4())
    sn = hello["sn"]
    await e.runtime.submit(sn, "configure", configured(profile, codec, fps))
    assert await e.runtime.submit(
        sn, "incoming", decode(hello, sn, hello["enrollment_id"])
    )
    offer = copy.deepcopy(e.sent[-1])
    proof = {**offer, "type": "camera_enrollment_proof", "admission_high_water": 41}
    assert await e.runtime.submit(
        sn, "incoming", decode(proof, sn, hello["enrollment_id"])
    )
    return hello, offer, proof, copy.deepcopy(e.sent[-1])


@pytest.mark.anyio
@pytest.mark.parametrize("codec", ["h264", "h265"])
@pytest.mark.parametrize("profile", ["low", "default"])
@pytest.mark.parametrize("fps", [20, 25, 120])
async def test_complete05_enrollment_and_unchanged_ctlv1_lifecycle(
    env, codec, profile, fps
):
    hello, offer, proof, commit = await enrolled(env, profile, codec, fps)
    assert (
        offer["revision"] == ENROLLMENT05
        and offer["camera_contract_revision"] == MEDIA14
    )
    assert (
        offer["cadence_revision"] == CADENCE03
        and commit["descriptor"] == offer["descriptor"]
    )
    assert offer["descriptor"]["tracks"][0]["fps"] == fps
    assert "cadence_revision" not in offer["descriptor"]
    query = await ready(env, hello["sn"])
    start = await env.runtime.submit(
        hello["sn"],
        "start",
        {
            "sn": hello["sn"],
            "command_id": str(uuid4()),
            "lease_id": str(uuid4()),
            "stream_instance_id": str(uuid4()),
            "descriptor_sha256": digest(offer["descriptor"]),
            "readiness_nonce": query["readiness_nonce"],
        },
    )
    validate(start)
    assert start["profile"] == "default" and start["mode"] == "usb-camera"
    identity = {k: start[k] for k in ("sn", "lease_id", "stream_instance_id")}
    env.tick[0] += 1000
    await env.runtime.submit(hello["sn"], "renew", identity)
    await env.runtime.submit(hello["sn"], "stop", identity)
    assert env.store.row.state["active"] is None
    load_state(copy.deepcopy(env.store.row.state))


@pytest.mark.anyio
async def test_selection_change_retires04_cached_commit_without_resetting_floor(env):
    hello, offer, old_proof, _ = await enrolled04(env)
    before = copy.deepcopy(env.store.row.state)
    sn = hello["sn"]
    assert before.get("completed")
    await env.runtime.submit(sn, "configure", configured())
    after = env.store.row.state
    assert after["counter"] == before["counter"] and after["boot"] == before["boot"]
    assert after["retired"] == before["retired"] and not after.get("completed")
    sent = len(env.sent)
    assert not await env.runtime.submit(sn, "incoming", old_proof)
    assert len(env.sent) == sent and not env.store.row.state["enrolled"]
    assert not await env.runtime.submit(sn, "incoming", hello)
    new_hello = fixture("hello")
    new_hello["enrollment_id"] = str(uuid4())
    assert await env.runtime.submit(sn, "incoming", new_hello)
    new_offer = copy.deepcopy(env.sent[-1])
    old_mixed = {
        **new_offer,
        "type": "camera_enrollment_proof",
        "admission_high_water": 41,
        "revision": "camera-enrollment/0.4.0-proposed",
        "camera_contract_revision": "siplite-camera/1.3.0",
        "cadence_revision": "camera-cadence/0.2.0-proposed",
    }
    validate(old_mixed)  # Well-formed old packet still cannot match new pending offer.
    pending = copy.deepcopy(env.store.row.state["pending"])
    assert not await env.runtime.submit(sn, "incoming", old_mixed)
    assert env.store.row.state["pending"] == pending
    assert env.store.row.state["counter"] == before["counter"]


def test_header_bundle_and_stored_attempt_revision_are_fenced():
    from api.internal_v1.remote_input import require_record_camera_headers

    def request(headers):
        return Request(
            {
                "type": "http",
                "headers": [
                    (k.lower().encode(), v.encode()) for k, v in headers.items()
                ],
            }
        )

    assert selected_headers(headers5()) == SELECTED5
    for name in headers5():
        mixed = headers5()
        mixed[name] = headers4()[name] if headers4()[name] != mixed[name] else "wrong"
        with pytest.raises(ValueError):
            selected_headers(mixed)
    d = configured()["descriptor"]
    require_record_camera_headers(request(headers5()), d, initial=True)
    require_record_camera_headers(request(headers5()), d, selection=SELECTED5)
    with pytest.raises(HTTPException):
        require_record_camera_headers(request(headers4()), d, selection=SELECTED5)
    with pytest.raises(HTTPException):
        require_record_camera_headers(request(headers5()), d, selection=SELECTED4)


@pytest.mark.anyio
@pytest.mark.parametrize("fps", [25, 120])
async def test_projection14_requires_its_own_observation_and_server_receipt(env, fps):
    payload = gauge(fps)
    validate_gauge(payload)
    session = SimpleNamespace(
        scalar=AsyncMock(
            side_effect=[
                SimpleNamespace(app_connect=True, is_blocked=False),
                SimpleNamespace(gauges=payload, updated_at=datetime.now(UTC)),
            ]
        )
    )
    view = await camera_capability(
        session,
        4623,
        authorized_sn="fixture",
        native=True,
        media_version=3,
        camera_revision=MEDIA14,
    )
    assert view.fresh and view.camera_observation["actual_track"]["fps"] == fps
    assert view.camera_capabilities == CAPABILITIES5
    assert view.camera["actual_track"] is None
    validate14("camera_observation", view.camera_observation)


@pytest.mark.anyio
async def test_http14_selection_and_response_models(monkeypatch):
    from api.internal_v1 import remote_input as api
    from core.models import db_helper

    monkeypatch.setattr(settings.auth, "internal_service_key", "cadence03-fixture-key")
    monkeypatch.setattr(api.DeviceRepo, "get_device_id", AsyncMock(return_value=4623))

    async def session():
        yield SimpleNamespace(
            scalar=AsyncMock(
                side_effect=[
                    SimpleNamespace(app_connect=True, is_blocked=False),
                    SimpleNamespace(gauges=gauge(25), updated_at=datetime.now(UTC)),
                ]
            )
        )

    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[db_helper.session_getter] = session
    headers = {
        **headers5(),
        "X-Internal-Service-Key": "cadence03-fixture-key",
        "X-Org-Id": "1",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/remote-input/devices/fixture/video-capabilities", headers=headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["camera_contract_revision"] == MEDIA14
        assert response.json()["camera_capabilities"] == CAPABILITIES5
        for header in headers5():
            partial = {key: value for key, value in headers.items() if key != header}
            response = await client.get(
                "/remote-input/devices/fixture/video-capabilities", headers=partial
            )
            assert response.status_code == 422, (header, response.text)
    from .test_camera_negotiated import epoch_and_lease

    old, _ = epoch_and_lease()
    body = old.start
    body.update(contract_version=3, descriptor=configured()["descriptor"])
    state = CameraStateView.from_record(
        {
            "start": body,
            "selection": SELECTED5,
            "media_clock_id": str(uuid4()),
            "result": "started",
            "state": "running",
        }
    )
    assert isinstance(state, CameraStateView14) and state.cadence_revision == CADENCE03
