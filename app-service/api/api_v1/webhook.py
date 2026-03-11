from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from core import settings
from core.logging_config import setup_module_logger
from core.models import db_helper
from core.crud.webhook_repo import WebhookRepo
from core.schemas.webhook import WebhookCreateUpdate, WebhookResponse
from api.api_v1.api_depends import Org_dep  # ← org_id из API-ключа

log = setup_module_logger(__name__, "api_webhooks.log")
# Описание для роутера — можно добавить кратко + ссылку
WEBHOOKS_DESCRIPTION = """
# 🌐 Вебхуки

Управление вебхуками для интеграции событий с внешними системами.

- Поддерживаемые типы: `msg-event`, `msg-task-result`
- Организация определяется по `x-api-key`
- Максимум вебхуков на организацию: настраивается через `APP_CONFIG__WEBHOOK__MAX_PER_ORG`

📄 [Полная документация по вебхукам](https://gitverse.ru/Oleg_Lebedev_ru/iot-rpc-rest-app/content/master/docs/webhooks.md)
"""

router = APIRouter(
    prefix=settings.api.v1.webhooks,
    tags=["Webhooks"],
    # description=WEBHOOKS_DESCRIPTION,  # ← Появится в Swagger
)


SUPPORTED_EVENT_TYPES = ["msg-event", "msg-task-result"]


@router.get("/", response_model=list[WebhookResponse])
async def get_webhooks(
    session: Annotated[AsyncSession, Depends(db_helper.session_getter)],
    org_id: Org_dep,
):
    """
    Получить все вебхуки текущей организации (по API-ключу)
    """
    repo = WebhookRepo(session)
    webhooks = await repo.get_all_by_org(org_id)
    return webhooks


@router.put("/{event_type}", response_model=WebhookResponse)
async def set_webhook(
    session: Annotated[AsyncSession, Depends(db_helper.session_getter)],
    event_type: str,
    data: WebhookCreateUpdate,
    org_id: Org_dep,
):
    """
    Установить или обновить вебхук для типа события.
    org_id берётся из API-ключа.
    """
    if event_type not in SUPPORTED_EVENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported event_type. Use one of: {SUPPORTED_EVENT_TYPES}",
        )

    repo = WebhookRepo(session)
    try:
        webhook = await repo.create_or_update(
            org_id=org_id,
            event_type=event_type,
            url=str(data.url),
            headers=data.headers,
            is_active=data.is_active,
        )
        await session.commit()
        return webhook
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/{event_type}")
async def delete_webhook(
    session: Annotated[AsyncSession, Depends(db_helper.session_getter)],
    event_type: str,
    org_id: Org_dep,
):
    """
    Удалить вебхук по типу события.
    org_id берётся из API-ключа.
    """
    if event_type not in SUPPORTED_EVENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported event_type: {event_type}",
        )

    repo = WebhookRepo(session)
    deleted = await repo.delete(org_id, event_type)
    if not deleted:
        raise HTTPException(status_code=404, detail="Webhook not found")
    await session.commit()
    return {"message": "Webhook deleted"}
