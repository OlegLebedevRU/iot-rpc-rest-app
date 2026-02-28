# crud/cell.py
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import Cell, Postamat, Device, DeviceOrgBind
from core.schemas.cell import CellCreate, CellUpdate


class CRUDCell:
    async def get_by_id(
        self,
        db: AsyncSession,
        cell_id: int,
        *,
        postamat_id: Optional[int] = None,
        org_id: Optional[int] = None,
        #     include_deleted: bool = False,
    ) -> Optional[Cell]:
        stmt = select(Cell).where(Cell.id == cell_id)
        #    if not include_deleted:
        #        stmt = stmt.where(Cell.is_deleted == False)
        if postamat_id is not None:
            stmt = stmt.where(Cell.postamat_id == postamat_id)
        if org_id is not None:
            stmt = (
                stmt.join(Cell.postamat)
                .join(Postamat.device)
                .join(Device.org_bind)
                .where(DeviceOrgBind.org_id == org_id)
            )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @classmethod
    async def get_multi_by_postamat(
        cls,
        db: AsyncSession,
        *,
        postamat_id: int,
        skip: int = 0,
        limit: int = 100,
        #    include_deleted: bool = False,
        org_id: Optional[int] = None,
    ) -> List[Cell]:
        stmt = select(Cell).where(Cell.postamat_id == postamat_id)
        # if not include_deleted:
        #     stmt = stmt.where(Cell.is_deleted == False)
        if org_id is not None:
            stmt = (
                stmt.join(Cell.postamat)
                .join(Postamat.device)
                .join(Device.org_bind)
                .where(DeviceOrgBind.org_id == org_id)
            )
        stmt = stmt.offset(skip).limit(limit).order_by(Cell.number)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def create(
        self,
        db: AsyncSession,
        obj_in: CellCreate,
        *,
        postamat_id: int,
        org_id: Optional[int] = None,
    ) -> Optional[Cell]:
        # Проверяем, существует ли Postamat и принадлежит ли org_id
        postamat_stmt = select(Postamat).where(Postamat.id == postamat_id)
        if org_id is not None:
            postamat_stmt = (
                postamat_stmt.join(Postamat.device)
                .join(Device.org_bind)
                .where(DeviceOrgBind.org_id == org_id)
            )
        postamat_result = await db.execute(postamat_stmt)
        postamat = postamat_result.scalar_one_or_none()
        if not postamat:
            return None  # Постамат не найден или нет доступа

        db_obj = Cell(
            postamat_id=postamat_id,
            number=obj_in.number,
            size_code=obj_in.size_code,
            alias=obj_in.alias,
            is_locked=obj_in.is_locked,
            attributes=obj_in.attributes or {},
        )
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def update(
        self, db: AsyncSession, *, db_obj: Cell, obj_in: CellUpdate | dict
    ) -> Cell:
        update_data = (
            obj_in
            if isinstance(obj_in, dict)
            else obj_in.model_dump(exclude_unset=True)
        )
        for field in update_data:
            if hasattr(db_obj, field):
                setattr(db_obj, field, update_data[field])
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    # ✅ remove: полное удаление (каскадно через ORM)
    async def remove(
        self,
        db: AsyncSession,
        *,
        cell_id: int,
        postamat_id: int,
        org_id: Optional[int] = None,
    ) -> bool:
        obj = await self.get_by_id(
            db,
            cell_id=cell_id,
            postamat_id=postamat_id,
            org_id=org_id,
        )
        if obj:
            await db.delete(obj)
            await db.commit()
            return True
        return False


cell = CRUDCell()
