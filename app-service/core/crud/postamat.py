from typing import Optional, List

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.models import Postamat, Device, DeviceOrgBind
from core.schemas.postamat import PostamatCreate, PostamatUpdate


class CRUDPostamat:

    @classmethod
    async def get_by_id(
        cls,
        db: AsyncSession,
        postamat_id: int,
        *,
        org_id: Optional[int] = None,
        with_device: bool = False,
        include_deleted: bool = False,
    ) -> Optional[Postamat]:
        stmt = select(Postamat).where(Postamat.id == postamat_id)
        if not include_deleted:
            stmt = stmt.where(Postamat.is_deleted == False)

        if org_id is not None:
            stmt = (
                stmt.join(Postamat.device)
                .join(Device.org_bind)
                .where(DeviceOrgBind.org_id == org_id)
            )

        if with_device:
            stmt = stmt.options(selectinload(Postamat.device))

        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_device_id(
        self,
        db: AsyncSession,
        device_id: int,
        *,
        org_id: Optional[int] = None,
        include_deleted: bool = False,
    ) -> Optional[Postamat]:
        stmt = select(Postamat).where(Postamat.device_id == device_id)
        if not include_deleted:
            stmt = stmt.where(Postamat.is_deleted == False)

        if org_id is not None:
            stmt = (
                stmt.join(Postamat.device)
                .join(Device.org_bind)
                .where(DeviceOrgBind.org_id == org_id)
            )

        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_multi(
        self,
        db: AsyncSession,
        *,
        skip: int = 0,
        limit: int = 100,
        org_id: Optional[int] = None,
        include_deleted: bool = False,
    ) -> List[Postamat]:
        stmt = select(Postamat)
        if not include_deleted:
            stmt = stmt.where(Postamat.is_deleted == False)

        if org_id is not None:
            stmt = (
                stmt.join(Postamat.device)
                .join(Device.org_bind)
                .where(DeviceOrgBind.org_id == org_id)
            )

        stmt = stmt.offset(skip).limit(limit).order_by(Postamat.id)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    # ... остальные методы (create, update и т.д.) без изменений ...

    async def create(
        self,
        db: AsyncSession,
        obj_in: PostamatCreate,
    ) -> Postamat:
        db_obj = Postamat(
            device_id=obj_in.device_id,
            name=obj_in.name,
            address=obj_in.address,
            location=obj_in.location,
        )
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def update(
        self, db: AsyncSession, *, db_obj: Postamat, obj_in: PostamatUpdate | dict
    ) -> Postamat:
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

    async def soft_delete(
        self, db: AsyncSession, *, postamat_id: int, org_id: Optional[int] = None
    ) -> bool:
        """
        Мягкое удаление постамата: помечает is_deleted = True.
        Проверяет принадлежность к org_id перед удалением.
        """
        stmt = select(Postamat).where(
            Postamat.id == postamat_id, Postamat.is_deleted == False
        )
        if org_id is not None:
            stmt = (
                stmt.join(Postamat.device)
                .join(Device.org_bind)
                .where(DeviceOrgBind.org_id == org_id)
            )

        result = await db.execute(stmt)
        postamat = result.scalar_one_or_none()

        if not postamat:
            return False  # Не найден или нет прав

        postamat.is_deleted = True
        postamat.deleted_at = func.now()
        db.add(postamat)
        await db.commit()
        return True

    async def restore(
        self, db: AsyncSession, *, postamat_id: int, org_id: Optional[int] = None
    ) -> bool:
        """
        Восстановление постамата из мягкого удаления.
        Проверяет принадлежность к org_id.
        """
        stmt = select(Postamat).where(
            Postamat.id == postamat_id, Postamat.is_deleted == True
        )
        if org_id is not None:
            stmt = (
                stmt.join(Postamat.device)
                .join(Device.org_bind)
                .where(DeviceOrgBind.org_id == org_id)
            )

        result = await db.execute(stmt)
        postamat = result.scalar_one_or_none()

        if not postamat:
            return False  # Не найден или нет прав

        postamat.is_deleted = False
        postamat.deleted_at = func.now()
        db.add(postamat)
        await db.commit()
        return True

    async def remove(
        self, db: AsyncSession, *, postamat_id: int, org_id: Optional[int] = None
    ) -> bool:
        obj = await self.get_by_id(db, postamat_id, org_id=org_id, include_deleted=True)
        if obj:
            await db.delete(obj)
            await db.commit()
            return True
        return False


# Единый экземпляр CRUD
postamat = CRUDPostamat()
