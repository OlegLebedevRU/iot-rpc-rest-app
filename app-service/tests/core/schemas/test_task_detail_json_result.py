from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from sqlalchemy import JSON, create_engine, select, true
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, aliased, mapped_column

from core.crud.dev_tasks_repo import TasksRepository


@pytest.mark.anyio
async def test_task_detail_deduplicates_identity_with_unhashable_payload():
    class Base(DeclarativeBase):
        pass

    class Record(Base):
        __tablename__ = "task_detail_fixture"
        id: Mapped[str] = mapped_column(primary_key=True)
        payload: Mapped[dict] = mapped_column(JSON)

    task_id = "135a4120-9ba6-4f6c-8cac-4baf5df8f1df"
    payload = {"dt": [{"pin": "000000"}]}
    engine = create_engine("sqlite://")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            session.add_all(
                [Record(id=task_id, payload=payload), Record(id="binding", payload={})]
            )
            session.commit()
            # Two joined binding rows; ORM JSON has the same non-hashable
            # uniqueness behavior as the production JSONB projection.
            result = session.execute(
                select(Record.id, Record.payload)
                .join(aliased(Record), true())
                .where(Record.id == task_id)
            )
            empty_results = session.execute(
                select(Record.id).where(Record.id == "none")
            )
            async_session = AsyncMock()
            async_session.execute.side_effect = [result, empty_results]
            task, results = await TasksRepository.get_task(
                async_session, UUID(task_id), org_id=1
            )
            assert task == {"id": task_id, "payload": payload}
            assert results == []
    finally:
        engine.dispose()
