from __future__ import annotations

import asyncio
import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from core.models import OrgReservation
from core.schemas.provisioning import OrgReservationRequest
from core.services.org_reservation import reserve_org_id


class ReservationStore:
    def __init__(self, occupied: set[int]) -> None:
        self.occupied = occupied
        self.reservations: dict[str, OrgReservation] = {}
        self.lock = asyncio.Lock()

    def session(self) -> ReservationSession:
        return ReservationSession(self)


class ReservationSession:
    def __init__(self, store: ReservationStore) -> None:
        self.store = store
        self.pending: OrgReservation | None = None

    async def execute(self, stmt: object) -> None:
        assert "pg_advisory_xact_lock" in str(stmt)
        await self.store.lock.acquire()

    async def get(self, model: type, operation_id: str) -> OrgReservation | None:
        assert model is OrgReservation
        return self.store.reservations.get(operation_id)

    async def scalar(self, stmt: object) -> int | None:
        sql = str(stmt)
        if "max(tb_orgs.org_id)" in sql:
            return max(self.store.occupied, default=0)
        params = stmt.compile(dialect=postgresql.dialect()).params
        candidate = int(params["org_id"])
        if candidate in self.store.occupied:
            return None
        self.store.occupied.add(candidate)
        return candidate

    def add(self, reservation: OrgReservation) -> None:
        self.pending = reservation

    async def commit(self) -> None:
        if self.pending is not None:
            self.store.reservations[self.pending.operation_id] = self.pending
        self.store.lock.release()

    async def rollback(self) -> None:
        if self.store.lock.locked():
            self.store.lock.release()


@pytest.mark.asyncio
async def test_reservations_skip_iot_orgs_and_are_unique_under_concurrency() -> None:
    store = ReservationStore({1, 2, 3, 1000})
    first, second = await asyncio.gather(
        reserve_org_id(
            store.session(),
            OrgReservationRequest(operation_id="registration:1", minimum_org_id=4),
        ),
        reserve_org_id(
            store.session(),
            OrgReservationRequest(operation_id="registration:2", minimum_org_id=4),
        ),
    )
    assert {first.org_id, second.org_id} == {1001, 1002}
    assert not first.replayed and not second.replayed


@pytest.mark.asyncio
async def test_replay_keeps_original_id_after_minimum_changes() -> None:
    store = ReservationStore({4})
    first = await reserve_org_id(
        store.session(),
        OrgReservationRequest(operation_id="registration:7", minimum_org_id=5),
    )
    assert first.org_id == 5
    replay_session = store.session()
    second = await reserve_org_id(
        replay_session,
        OrgReservationRequest(operation_id="registration:7", minimum_org_id=12),
    )
    assert second.org_id == 5 and second.replayed
    await replay_session.rollback()
    assert len(store.reservations) == 1


@pytest.mark.asyncio
async def test_explicit_id_conflict_does_not_reserve() -> None:
    store = ReservationStore({4})
    session = store.session()
    with pytest.raises(HTTPException) as exc:
        await reserve_org_id(
            session,
            OrgReservationRequest(operation_id="admin:4", requested_org_id=4),
        )
    assert exc.value.status_code == 409
    assert exc.value.detail == {"code": "org_id_already_in_use"}
    await session.rollback()
    assert not store.reservations


@pytest.mark.asyncio
async def test_same_operation_cannot_change_explicit_id() -> None:
    store = ReservationStore(set())
    await reserve_org_id(
        store.session(),
        OrgReservationRequest(operation_id="admin:7", requested_org_id=7),
    )
    replay_session = store.session()
    with pytest.raises(HTTPException) as exc:
        await reserve_org_id(
            replay_session,
            OrgReservationRequest(operation_id="admin:7", requested_org_id=8),
        )
    assert exc.value.detail == {"code": "org_reservation_operation_conflict"}
    await replay_session.rollback()
