"""Opt-in lock/rollback checks in a disposable schema of camera_runtime_test."""

import asyncio
import copy
import os
from uuid import uuid4

import pytest
from core.camera.runtime_state import initial_state
from core.camera.authority_state import load_state
from core.camera.runtime_store import AuthorityStore
from core.models.camera_authority import CameraAuthority
from core.models.devices import Device
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

URL = os.environ.get("CAMERA_RUNTIME_TEST_DB_URL", "")
pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not URL, reason="isolated camera_runtime_test PostgreSQL not configured"
    ),
]


async def test_postgres_fence_serialization_rollback_and_missing_state():
    assert URL.endswith("/camera_runtime_test"), "Never run on a production database"
    schema = "camera_runtime_" + uuid4().hex
    engine = create_async_engine(
        URL, execution_options={"schema_translate_map": {None: schema}}
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    store = AuthorityStore(sessions)
    original_boot, retired_boot = str(uuid4()), str(uuid4())
    legacy = {
        **initial_state(),
        "version": 1,
        "counter": 100,
        "boot": original_boot,
        "retired": [retired_boot],
    }
    try:
        async with engine.begin() as connection:
            await connection.execute(CreateSchema(schema))
            await connection.run_sync(lambda conn: Device.__table__.create(conn))
            await connection.run_sync(
                lambda conn: CameraAuthority.__table__.create(conn)
            )
            await connection.execute(insert(Device).values(device_id=1, sn="fixture"))
            await connection.execute(
                insert(CameraAuthority).values(sn="fixture", state=legacy)
            )

        async def advance():
            async with store.locked("fixture") as (row, _):
                counter = row.state["counter"]
                await asyncio.sleep(0.005)
                row.state["counter"] = counter + 1

        await asyncio.gather(*(advance() for _ in range(8)))
        upgraded = await store.get("fixture")
        assert upgraded["counter"] == 108 and upgraded["version"] == 2
        assert upgraded["boot"] == original_boot and upgraded["retired"] == [
            retired_boot
        ]
        original = await store.get("fixture")
        with pytest.raises(RuntimeError):
            async with store.locked("fixture") as (row, _):
                row.state["counter"] = 0
                raise RuntimeError("transaction interrupted")
        assert await store.get("fixture") == original
        with pytest.raises(ValueError, match="authority_corrupt"):
            async with store.locked("fixture") as (row, _):
                del row.state["counter"]
        assert await store.get("fixture") == original
        async with store.locked("fixture") as (row, _):
            row.state["retired"].append(str(uuid4()))
            copy_before_restart = copy.deepcopy(row.state)
        restarted = AuthorityStore(sessions)
        assert await restarted.get("fixture") == copy_before_restart
        with pytest.raises(ValueError, match="not_provisioned"):
            async with restarted.locked("missing"):
                pass
    finally:
        async with engine.begin() as connection:
            await connection.execute(DropSchema(schema, cascade=True))
        await engine.dispose()


async def test_real_migration_seeds_and_only_new_device_insert_creates_authority(
    monkeypatch,
):
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import func, select, text

    assert URL.endswith("/camera_runtime_test")
    schema = "camera_migration_" + uuid4().hex
    engine = create_async_engine(URL)
    path = next(
        (Path(__file__).resolve().parents[3] / "alembic/versions").glob(
            "*0013_camera_authority*"
        )
    )
    spec = importlib.util.spec_from_file_location("camera_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        async with engine.begin() as connection:
            await connection.execute(CreateSchema(schema))
            await connection.execute(
                text('SET LOCAL search_path = "' + schema + '", public')
            )
            await connection.run_sync(lambda conn: Device.__table__.create(conn))
            await connection.execute(insert(Device).values(device_id=1, sn="original"))

            def upgrade(conn):
                monkeypatch.setattr(
                    module, "op", Operations(MigrationContext.configure(conn))
                )
                module.upgrade()

            await connection.run_sync(upgrade)
            state = (
                await connection.execute(
                    select(CameraAuthority.state).where(
                        CameraAuthority.sn == "original"
                    )
                )
            ).scalar_one()
            assert state["version"] == 1  # Immutable migration stays unchanged.
            assert load_state(state) == initial_state()
            await connection.execute(
                insert(Device).values(device_id=2, sn="new-device")
            )
            assert (
                await connection.execute(
                    select(func.count()).select_from(CameraAuthority)
                )
            ).scalar_one() == 2
            # A missing fence is not recreated by ordinary device UPDATE/upsert.
            await connection.execute(
                text("DELETE FROM tb_camera_authorities WHERE sn='original'")
            )
            await connection.execute(
                text("UPDATE tb_devices SET device_id=1 WHERE sn='original'")
            )
            assert (
                await connection.execute(
                    select(func.count()).select_from(CameraAuthority)
                )
            ).scalar_one() == 1
            # Device CRUD/renaming remains compatible, while old SN fences survive.
            await connection.execute(
                text(
                    "UPDATE tb_camera_authorities SET state=jsonb_set(state,'{counter}','42') WHERE sn='new-device'"
                )
            )
            await connection.execute(
                text("UPDATE tb_devices SET sn='renamed-device' WHERE sn='new-device'")
            )
            assert (
                await connection.execute(
                    select(CameraAuthority.state).where(
                        CameraAuthority.sn == "new-device"
                    )
                )
            ).scalar_one()["counter"] == 42
            await connection.execute(
                insert(Device).values(device_id=3, sn="new-device")
            )
            assert (
                await connection.execute(
                    select(CameraAuthority.state).where(
                        CameraAuthority.sn == "new-device"
                    )
                )
            ).scalar_one()["counter"] == 42
            with pytest.raises(RuntimeError, match="durable"):
                module.downgrade()
    finally:
        async with engine.begin() as connection:
            await connection.execute(DropSchema(schema, cascade=True))
        await engine.dispose()


@pytest.mark.parametrize("native04", [False, True, "nominal05"])
async def test_real_postgres_actor_takeover_preserves_floors_and_fences_egress(
    monkeypatch,
    native04,
):
    import json
    from pathlib import Path

    from core.camera.runtime import CameraRuntime
    from core.camera.runtime_wire import ADMISSION, ENROLLMENT, digest, validate
    from core.config import settings
    from sqlalchemy import func, update

    assert URL.endswith("/camera_runtime_test")
    monkeypatch.setattr(settings.camera, "monotonic_runtime_enabled", True)
    schema = "camera_actor_" + uuid4().hex
    engine = create_async_engine(
        URL, execution_options={"schema_translate_map": {None: schema}}
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    store = AuthorityStore(sessions)
    sent = []
    sn = "fixture"
    boot = str(uuid4())

    async def send(route, message, ttl):
        assert route == sn and ttl > 0
        validate(message)
        persisted = await store.get(sn)
        assert any(entry["message"] == message for entry in persisted["outbox"])
        sent.append(copy.deepcopy(message))

    async def authority(route, message):
        assert route == sn
        return 60000

    try:
        async with engine.begin() as connection:
            await connection.execute(CreateSchema(schema))
            await connection.run_sync(lambda conn: Device.__table__.create(conn))
            await connection.run_sync(
                lambda conn: CameraAuthority.__table__.create(conn)
            )
            await connection.execute(insert(Device).values(device_id=1, sn=sn))
            await connection.execute(
                insert(CameraAuthority).values(sn=sn, state=initial_state())
            )
        runtime = CameraRuntime(store, send, authority)
        d = json.loads(
            (
                Path(__file__).resolve().parents[4]
                / "contracts/siplite-camera-v1/fixtures/native_hevc_level51.json"
            ).read_text()
        )["payload"]["descriptor"]
        config = {
            "descriptor": d,
            "binding": {
                "source_id": d["source_id"],
                "physical_camera_mac": "02:00:00:00:00:01",
                "path_generation": "port2/1/1",
                "codec": "h265",
                "descriptor_sha256": digest(d),
            },
        }
        if native04:
            if native04 == "nominal05":
                from .test_camera_cadence03 import configured, fixture
            else:
                from .test_camera_cadence02 import configured, fixture

            config = configured()
            d = config["descriptor"]
        await runtime.submit(sn, "configure", config)

        async def enroll(owner):
            h = {
                "revision": ENROLLMENT,
                "type": "camera_enrollment_hello",
                "sn": sn,
                "boot_id": boot,
                "enrollment_id": str(uuid4()),
                "admission_high_water": 41,
                "supported_ctl": [ADMISSION],
            }
            if native04:
                h = {
                    **fixture("hello"),
                    "sn": sn,
                    "boot_id": boot,
                    "enrollment_id": str(uuid4()),
                }
            assert await owner.submit(sn, "incoming", h)
            proof = {
                **sent[-1],
                "type": "camera_enrollment_proof",
                "admission_high_water": 41,
            }
            assert await owner.submit(sn, "incoming", proof)
            return proof

        old_proof = await enroll(runtime)
        q = await runtime.submit(sn, "readiness", {"sn": sn})
        result = {
            k: v for k, v in q.items() if k not in ("issued_at_ms", "expires_at_ms")
        }
        result.update(type="camera_readiness_result", status="ready")
        assert await runtime.submit(sn, "incoming", result)
        command = await runtime.submit(
            sn,
            "start",
            {
                "sn": sn,
                "command_id": str(uuid4()),
                "lease_id": str(uuid4()),
                "stream_instance_id": str(uuid4()),
                "descriptor_sha256": digest(d),
                "readiness_nonce": q["readiness_nonce"],
            },
        )
        assert command["admission_seq"] == 42
        await runtime.submit(sn, "release", {"command_id": command["command_id"]})
        before = await store.get(sn)
        if native04 == "nominal05":
            from .camera_worker_recycle import assert_web_recycles_while_issuer_survives

            await assert_web_recycles_while_issuer_survives(runtime, store, sn)
        async with sessions() as session, session.begin():
            await session.execute(
                update(CameraAuthority).values(
                    owner_until=func.now() - __import__("datetime").timedelta(seconds=1)
                )
            )
        successor = CameraRuntime(store, send, authority)
        await successor.pump(sn)
        state = await store.get(sn)
        assert (
            state["generation"] == before["generation"] + 1 and state["counter"] == 42
        )
        assert (
            state["epoch"] != before["epoch"]
            and not state["active"]
            and not state["enrolled"]
        )
        count = len(sent)
        await runtime.flush(sn)
        assert len(sent) == count
        assert not await successor.submit(sn, "incoming", old_proof)
        await enroll(successor)
        assert sent[-1]["admission_floor"] == 42
        new = await successor.submit(sn, "readiness", {"sn": sn})
        assert new["admission_seq"] == 43
    finally:
        async with engine.begin() as connection:
            await connection.execute(DropSchema(schema, cascade=True))
        await engine.dispose()
