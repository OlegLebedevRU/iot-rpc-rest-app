"""Real PostgreSQL tests; only an explicitly supplied localhost test DB is allowed."""

from __future__ import annotations

import importlib.util
import os
import secrets
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi_pagination import add_pagination
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from api.api_v1.api_depends import get_org_id_dependency
from api.api_v1.device_events import router as public_router
from api.internal_v1.device_events import router as internal_router
from core.config import settings
from core.crud.dev_events_repo import EventRepository
from core.models import Base, DevEvent, Device, DeviceOrgBind, Org, db_helper
from core.models.device_events import DeviceEventOffset
from core.schemas.device_events import DevEventBody, UserEventSearchRequest
from core.services.device_events import DeviceEventsService
from core.services.device_events_collect import DeviceEventsCollect


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def event_db():
    url = os.environ.get("IOT_EVENT_TEST_DATABASE_URL")
    if not url:
        pytest.skip(
            "Set IOT_EVENT_TEST_DATABASE_URL to an isolated localhost PostgreSQL"
        )
    parsed = make_url(url)
    if (
        parsed.host not in ("127.0.0.1", "localhost")
        or parsed.database != "iot_event_test"
    ):
        pytest.fail(
            "Refusing to run mutable event tests outside the dedicated local DB"
        )
    schema = "event_test_" + uuid4().hex
    admin = create_async_engine(url, poolclass=NullPool)
    async with admin.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(
        url,
        poolclass=NullPool,
        connect_args={"server_settings": {"search_path": schema}},
    )
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            session.add_all(
                [
                    Org(org_id=1),
                    Org(org_id=2),
                    Device(device_id=70001, sn="event-test-device"),
                ]
            )
            await session.commit()
            session.add(DeviceOrgBind(device_id=70001, org_id=1))
            await session.commit()
        yield factory, engine
    finally:
        await engine.dispose()
        async with admin.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


def event(number: int, **tags) -> DevEventBody:
    return DevEventBody(
        device_id=70001,
        event_type_code=999,
        dev_event_id=number,
        dev_timestamp=1790850000 + number,
        payload={"300": [{"446": '{"result":"ok"}', "447": 7, **tags}]},
    )


@pytest.mark.anyio
async def test_transfer_unknown_history_and_duplicate_owner(event_db):
    factory, _ = event_db
    async with factory() as session:
        assert await EventRepository.add_event(session, event(1))
        first = await session.scalar(select(DevEvent))
        assert first.org_id == 1
        session.add(
            DevEvent(
                device_id=70001,
                org_id=None,
                event_type_code=999,
                dev_event_id=0,
                dev_timestamp=datetime.now(UTC),
                payload={},
            )
        )
        await session.commit()
        svc = DeviceEventsService(session, org_id=1)
        assert [
            x.id
            for x in (
                await svc.search_user_events(UserEventSearchRequest(device_id=70001))
            ).items
        ] == [first.id]
        await session.execute(update(DeviceOrgBind).values(org_id=2))
        await session.commit()
        assert not (
            await svc.search_user_events(UserEventSearchRequest(device_id=70001))
        ).items
        assert not await EventRepository.add_event(session, event(1))
        await session.refresh(first)
        assert first.org_id == 1
        assert await EventRepository.add_event(session, event(2))
        tenant2 = DeviceEventsService(session, org_id=2)
        assert [
            x.dev_event_id
            for x in (
                await tenant2.search_user_events(
                    UserEventSearchRequest(device_id=70001)
                )
            ).items
        ] == [2]
        assert len(await tenant2.fields(70001, 999, 447, 120, 10)) == 1
        assert [
            x.dev_event_id for x in await tenant2.get_incremental_events(70001, 0, 10)
        ] == [2]
        await session.execute(update(DeviceOrgBind).values(org_id=1))
        await session.commit()
        assert [
            x.dev_event_id
            for x in (
                await svc.search_user_events(UserEventSearchRequest(device_id=70001))
            ).items
        ] == [1]
        assert [
            x.dev_event_id for x in await svc.get_incremental_events(70001, 0, 10)
        ] == [1]


@pytest.mark.anyio
async def test_filters_cursor_and_independent_readers(event_db):
    factory, _ = event_db
    external = str(uuid4())
    same_time = datetime.now(UTC)
    async with factory() as session:
        for n in range(1, 5):
            assert await EventRepository.add_event(
                session, event(n, **{"448": external.upper()})
            )
        assert await EventRepository.add_event(
            session, event(5, **{"448": str(uuid4())})
        )
        other = event(6)
        other.event_type_code = 75
        assert await EventRepository.add_event(session, other)
        await session.execute(update(DevEvent).values(created_at=same_time))
        session.add(DeviceEventOffset(device_id=70001, last_event_id=123456))
        await session.commit()
    request = UserEventSearchRequest(
        device_id=70001,
        correlation_id=UUID(external),
        events_include=[999],
        limit=2,
        created_from=same_time - timedelta(seconds=1),
        created_to=same_time + timedelta(seconds=1),
    )
    async with factory() as one, factory() as two:
        a = await EventRepository.search_user_events(one, 1, request)
        b = await EventRepository.search_user_events(two, 1, request)
        assert a == b and a.has_more
        assert [x.dev_event_id for x in a.items] == [1, 2]
        assert a.items[0].payload is not None
        assert a.items[0].payload["300"][0]["446"] == '{"result":"ok"}'
        next_request = request.model_copy(
            update={"after_event_id": a.next_after_event_id}
        )
        last = await EventRepository.search_user_events(one, 1, next_request)
        assert not last.has_more and [x.dev_event_id for x in last.items] == [3, 4]
        empty = await EventRepository.search_user_events(
            one,
            1,
            request.model_copy(update={"after_event_id": last.next_after_event_id}),
        )
        assert (
            empty.items == [] and empty.next_after_event_id == last.next_after_event_id
        )
        assert await one.scalar(select(DeviceEventOffset.last_event_id)) == 123456
        assert not one.new and not one.dirty
        assert not (await EventRepository.search_user_events(one, 2, request)).items
        assert not (
            await EventRepository.search_user_events(
                one, 1, request.model_copy(update={"created_to": same_time})
            )
        ).items


@pytest.mark.anyio
async def test_unknown_binding_is_not_inferred_from_payload(event_db):
    factory, _ = event_db
    async with factory() as session:
        e = event(1, org_id=2)
        e.device_id = 70002
        assert await EventRepository.add_event(session, e)
        saved = await session.scalar(select(DevEvent))
        assert saved.org_id is None
        assert saved.payload["300"][0]["org_id"] == 2


@pytest.mark.anyio
async def test_collector_uses_topic_identity_and_preserves_payload(
    event_db, monkeypatch
):
    factory, _ = event_db
    publish = AsyncMock()
    monkeypatch.setattr(
        "core.services.device_events_collect.topic_publisher.publish", publish
    )
    monkeypatch.setattr("core.services.device_events_collect.send_eva", AsyncMock())
    payload = {
        "200": 999,
        "org_id": 2,
        "300": [{"324": "another-device", "446": "text", "447": 0}],
    }
    msg = SimpleNamespace(
        headers={
            "event_type_code": "999",
            "dev_event_id": "1",
            "dev_timestamp": "1790850000",
        },
        body=json.dumps(payload).encode(),
    )
    async with factory() as session:
        await DeviceEventsCollect(session, sn="event-test-device", org_id=2).add(msg)
        row = await session.scalar(select(DevEvent))
        assert row is not None and row.device_id == 70001 and row.org_id == 1
        assert row.payload == payload
        assert publish.await_count == 1


@pytest.mark.anyio
async def test_http_tenant_auth_all_read_paths_and_validation(event_db, monkeypatch):
    factory, _ = event_db
    key = secrets.token_urlsafe(24)
    monkeypatch.setattr(settings.auth, "internal_service_key", key)
    app = FastAPI()
    app.include_router(internal_router, prefix="/api/internal/v1")
    app.include_router(public_router, prefix="/api/v1")
    add_pagination(app)

    async def session_dep():
        async with factory() as session:
            yield session

    app.dependency_overrides[db_helper.session_getter] = session_dep

    # Public auth itself is covered by test_auth_api_keys; exercise its tenant boundary here.
    async def public_org():
        return 2

    app.dependency_overrides[get_org_id_dependency] = public_org
    async with factory() as session:
        assert await EventRepository.add_event(session, event(1))
        oversize = event(2, **{"447": -2})
        assert oversize.payload is not None
        del oversize.payload["300"][0]["446"]
        assert await EventRepository.add_event(session, oversize)
    base = "/api/internal/v1" + settings.api.internal_v1.device_events
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        h = {"X-Internal-Service-Key": key, "X-Org-Id": "1"}
        response = await client.get(
            base + "/search", params={"device_id": 70001}, headers=h
        )
        assert response.status_code == 200
        assert len(response.json()["items"]) == 2
        tags = response.json()["items"][1]["payload"]["300"][0]
        assert tags == {"447": -2}
        assert (
            await client.get(base + "/search", params={"device_id": 70001})
        ).status_code == 403
        assert (
            await client.get(
                base + "/search",
                params={"device_id": 70001},
                headers={"X-Internal-Service-Key": key},
            )
        ).status_code == 400
        for extra in (
            {"correlation_id": "bad"},
            {"events_include": 75},
            {"limit": 101},
            {"after_event_id": 0},
            {"created_from": "2026-10-01T00:00:00"},
            {
                "created_from": "2026-10-02T00:00:00Z",
                "created_to": "2026-10-01T00:00:00Z",
            },
        ):
            r = await client.get(
                base + "/search", params={"device_id": 70001, **extra}, headers=h
            )
            assert r.status_code == 422, r.text
        for prefix, headers in (
            (base, {**h, "X-Org-Id": "2"}),
            ("/api/v1" + settings.api.v1.device_events, {}),
        ):
            r = await client.get(
                prefix + "/", params={"device_id": 70001}, headers=headers
            )
            assert r.status_code == 200 and r.json()["items"] == []
            r = await client.get(
                prefix + "/fields/",
                params={"device_id": 70001, "event_type_code": 999, "tag": 447},
                headers=headers,
            )
            assert r.status_code == 200 and r.json() == []
            r = await client.get(
                prefix + "/incremental",
                params={"device_id": 70001, "last_event_id": 0},
                headers=headers,
            )
            assert r.status_code == 200 and r.json() == []


@pytest.mark.anyio
async def test_migration_preserves_unknown_rows_and_old_writer(event_db):
    _, engine = event_db
    migration_path = next(
        (Path(__file__).parents[2] / "alembic/versions").glob("*0011_event_tenants*.py")
    )
    spec = importlib.util.spec_from_file_location(
        "event_tenants_migration", migration_path
    )
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    def apply(conn, direction):
        with Operations.context(MigrationContext.configure(conn)):
            getattr(migration, direction)()

    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE tb_dev_events DROP COLUMN org_id CASCADE"))
        await conn.execute(
            text(
                "INSERT INTO tb_dev_events (device_id,event_type_code,dev_event_id,payload) VALUES (70001,999,1,'{}')"
            )
        )
        await conn.run_sync(apply, "upgrade")
        row = (
            await conn.execute(text("SELECT dev_event_id,org_id FROM tb_dev_events"))
        ).one()
        assert row == (1, None)
        # Old collectors omitting the new column remain compatible during rollback.
        await conn.execute(
            text(
                "INSERT INTO tb_dev_events (device_id,event_type_code,dev_event_id,payload) VALUES (70001,999,2,'{}')"
            )
        )
        assert (
            await conn.scalar(
                text("SELECT count(*) FROM tb_dev_events WHERE org_id IS NULL")
            )
            == 2
        )
        await conn.run_sync(apply, "downgrade")
        assert await conn.scalar(text("SELECT count(*) FROM tb_dev_events")) == 2
        await conn.run_sync(apply, "upgrade")
