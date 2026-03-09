# services/postamat_service.py
from core.logging_config import setup_module_logger
from typing import Optional, List, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.crud.cell import CRUDCell as crud_cell
from core.crud.postamat import CRUDPostamat as crud_postamat
from core.models import Postamat, Cell, Device, DeviceOrgBind
from core.schemas.device_tasks import TaskCreate
from core.services.device_tasks import DeviceTasksService

# Настройка логгера
log = setup_module_logger(__name__, "srv_postamats.log")


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
            db=db,
            postamat_id=postamat_id,
            org_id=org_id,
            with_device=True,
            include_deleted=False,
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
            #    "created_at": db_postamat.created_at,
            #    "updated_at": db_postamat.updated_at,
            #    "is_deleted": db_postamat.is_deleted,
            #    "deleted_at": db_postamat.deleted_at,
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
                    #     "created_at": c.created_at,
                    "updated_at": c.updated_at,
                    #        "is_deleted": c.is_deleted,
                }
                for c in cells
            ],
        }

    async def get_all_postamats(
        self,
        db: AsyncSession,
        *,
        org_id: Optional[int] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[dict]:
        """
        Получить список всех постаматов (без ячеек) с опциональной фильтрацией по org_id.
        Использует CRUD-метод get_multi для получения данных.
        """
        # Получаем объекты Postamat через CRUD
        postamats = await crud_postamat.get_multi(
            db=db,
            org_id=org_id,
            skip=skip,
            limit=limit,
            with_device=True,
            include_deleted=False,  # Только активные постаматы
        )

        return [
            {
                "id": p.id,
                "device_id": p.device_id,
                "name": p.name,
                "address": p.address,
                "location": p.location,
                "created_at": p.created_at,
                "updated_at": p.updated_at,
                "device": (
                    {
                        "sn": p.device.sn,
                        "created_at": p.device.created_at,
                    }
                    if p.device
                    else None
                ),
            }
            for p in postamats
        ]

    async def create_command(
        self,
        db: AsyncSession,
        *,
        postamat_id: int,
        method: str,
        params: Dict,
        org_id: Optional[int] = None,
    ):
        """
        Создаёт задачу на устройство (постамат) через mapping метода в код.
        Использует device_task_service.create для фактического создания задачи.
        """
        # 1. Получаем постамат и проверяем принадлежность к орге
        db_postamat = await crud_postamat.get_by_id(
            db=db,
            postamat_id=postamat_id,
            org_id=org_id,
            with_device=True,
            include_deleted=False,
        )
        if not db_postamat:
            return None

        device_id = db_postamat.device_id

        # 2. Маппинг method -> method_code и формирование payload
        method_code = None
        payload = {}

        if method == "open_cells":
            method_code = 51
            cell_numbers = params.get("cell_numbers")
            if isinstance(cell_numbers, list):
                payload["dt"] = [{"cl": num} for num in cell_numbers]
            else:
                payload["dt"] = []
        else:
            # Для других методов можно добавить логику
            # Пока просто передаём params как payload
            method_code = 99  # Условный "кастомный" метод
            payload = params

        # 3. Формируем схему TaskCreate
        task_in = TaskCreate(
            device_id=int(device_id),
            method_code=method_code,
            payload=payload,
            ttl=1,
            priority=99,
            ext_task_id="0",
        )

        # 4. Передаём в device_task_service
        task = await DeviceTasksService(session=db, org_id=org_id).create(
            task_create=task_in
        )  # .create(session=db, task_in=task_in)
        return task

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
