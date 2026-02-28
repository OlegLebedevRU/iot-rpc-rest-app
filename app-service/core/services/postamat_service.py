# services/postamat_service.py
from typing import Optional, List, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.crud.cell import CRUDCell as crud_cell
from core.crud.postamat import CRUDPostamat as crud_postamat
from core.models import Postamat, Cell, Device, DeviceOrgBind


class PostamatService:
    async def get_with_cells(
        self,
        db: AsyncSession,
        *,
        postamat_id: int,
        org_id: Optional[int] = None,
        include_deleted_cells: bool = False,
    ) -> Optional[dict]:
        # Получаем постамат с проверкой по org_id
        db_postamat = await crud_postamat.get_by_id(
            db=db, postamat_id=postamat_id, org_id=org_id, with_device=True
        )
        if not db_postamat:
            return None

        # Получаем все ячейки постамата
        cells = await crud_cell.get_multi_by_postamat(
            db,
            postamat_id=postamat_id,  # include_deleted=include_deleted_cells
        )

        return {
            "id": db_postamat.id,
            "device_id": db_postamat.device_id,
            "name": db_postamat.name,
            "address": db_postamat.address,
            "location": db_postamat.location,
            "created_at": db_postamat.created_at,
            "updated_at": db_postamat.updated_at,
            "is_deleted": db_postamat.is_deleted,
            "deleted_at": db_postamat.deleted_at,
            "device": (
                {
                    "sn": db_postamat.device.sn,
                    "created_at": db_postamat.device.created_at,
                }
                if db_postamat.device
                else None
            ),
            "cells": [
                {
                    "id": c.id,
                    "number": c.number,
                    "size_code": c.size_code,
                    "alias": c.alias,
                    "is_locked": c.is_locked,
                    "attributes": c.attributes,
                    "created_at": c.created_at,
                    "updated_at": c.updated_at,
                    #        "is_deleted": c.is_deleted,
                }
                for c in cells
            ],
        }

    # 1️⃣ Переключить is_locked для одной ячейки
    async def toggle_lock_cell(
        self,
        db: AsyncSession,
        *,
        postamat_id: int,
        cell_id: int,
        is_locked: bool,
        org_id: Optional[int] = None,
    ) -> bool:
        """
        Устанавливает состояние is_locked у конкретной ячейки.
        Проверяет принадлежность ячейки к постамату и постамата к org_id.
        """
        # Проверяем, существует ли ячейка и принадлежит ли постамату и орге
        stmt = select(Cell).where(
            Cell.id == cell_id,
            Cell.postamat_id == postamat_id,
            #      Cell.is_deleted == False,
        )
        if org_id is not None:
            stmt = (
                stmt.join(Cell.postamat)
                .join(Postamat.device)
                .join(Device.org_bind)
                .where(DeviceOrgBind.org_id == org_id)
            )

        result = await db.execute(stmt)
        cell = result.scalar_one_or_none()
        if not cell:
            return False

        # Обновляем состояние
        cell.is_locked = is_locked
        db.add(cell)
        await db.commit()
        return True

    # 2️⃣ Переключить is_locked для нескольких ячеек
    #     [
    #   {"id": 1, "is_locked": true},
    #   {"id": 2, "is_locked": false}
    # ]
    async def toggle_lock_cells(
        self,
        db: AsyncSession,
        *,
        postamat_id: int,
        locks_data: List[Dict[str, bool]],  # [{"id": 1, "is_locked": True}, ...]
        org_id: Optional[int] = None,
    ) -> Dict[str, int]:
        """
        Массовое обновление is_locked для списка ячеек.
        Возвращает количество успешно обновлённых и неудачных.
        """
        success_count = 0
        failed_count = 0

        for item in locks_data:
            cell_id = item.get("id")
            is_locked = item.get("is_locked")
            if not isinstance(cell_id, int) or not isinstance(is_locked, bool):
                failed_count += 1
                continue

            try:
                updated = await self.toggle_lock_cell(
                    db,
                    postamat_id=postamat_id,
                    cell_id=cell_id,
                    is_locked=is_locked,
                    org_id=org_id,
                )
                if updated:
                    success_count += 1
                else:
                    failed_count += 1
            except Exception:
                failed_count += 1

        return {"success": success_count, "failed": failed_count}

    # 3️⃣ Обновить атрибуты конкретной ячейки
    async def update_cell_attributes(
        self,
        db: AsyncSession,
        *,
        postamat_id: int,
        cell_id: int,
        attributes: Dict,
        org_id: Optional[int] = None,
    ) -> bool:
        """
        Полностью заменяет или дополняет JSONB-поле attributes.
        """
        stmt = select(Cell).where(
            Cell.id == cell_id,
            Cell.postamat_id == postamat_id,
            #       Cell.is_deleted == False,
        )
        if org_id is not None:
            stmt = (
                stmt.join(Cell.postamat)
                .join(Postamat.device)
                .join(Device.org_bind)
                .where(DeviceOrgBind.org_id == org_id)
            )

        result = await db.execute(stmt)
        cell = result.scalar_one_or_none()
        if not cell:
            return False

        cell.attributes = {**(cell.attributes or {}), **attributes}
        db.add(cell)
        await db.commit()
        return True

    # 4️⃣ Обновить атрибуты нескольких ячеек
    #     [
    #   {"id": 1, "attributes": {"backlight": true, "temperature": 4}},
    #   {"id": 2, "attributes": {"door_sensor_ok": false}}
    # ]
    async def update_cells_attributes(
        self,
        db: AsyncSession,
        *,
        postamat_id: int,
        attrs_data: List[Dict],  # [{"id": 1, "attributes": {"light": True}}]
        org_id: Optional[int] = None,
    ) -> Dict[str, int]:
        """
        Массовое обновление атрибутов.
        Возвращает статистику.
        """
        success_count = 0
        failed_count = 0

        for item in attrs_data:
            cell_id = item.get("id")
            attributes = item.get("attributes")
            if not isinstance(cell_id, int) or not isinstance(attributes, dict):
                failed_count += 1
                continue

            try:
                updated = await self.update_cell_attributes(
                    db,
                    postamat_id=postamat_id,
                    cell_id=cell_id,
                    attributes=attributes,
                    org_id=org_id,
                )
                if updated:
                    success_count += 1
                else:
                    failed_count += 1
            except Exception:
                failed_count += 1

        return {"success": success_count, "failed": failed_count}


# Единый экземпляр сервиса
postamat_service = PostamatService()
