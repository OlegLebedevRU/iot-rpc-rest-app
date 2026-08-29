from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.internal_v1.internal_depends import Internal_Org_dep, Session_dep
from core import settings
from core.crud.webhook_repo import WebhookRepo
from core.logging_config import setup_module_logger
from core.schemas.webhook import WebhookCreateUpdate, WebhookResponse

log = setup_module_logger(__name__, "api_internal_webhooks.log")
router = APIRouter(
    prefix=settings.api.internal_v1.webhooks,
    tags=["Internal Webhooks"],
    include_in_schema=False,
)

SUPPORTED_EVENT_TYPES = ["msg-event", "msg-task-result"]


@router.get("/", response_model=list[WebhookResponse])
async def get_webhooks(
    session: Session_dep,
    org_id: Internal_Org_dep,
):
    repo = WebhookRepo(session)
    return await repo.get_all_by_org(org_id)


@router.put("/{event_type}", response_model=WebhookResponse)
async def set_webhook(
    session: Session_dep,
    event_type: str,
    data: WebhookCreateUpdate,
    org_id: Internal_Org_dep,
):
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
    session: Session_dep,
    event_type: str,
    org_id: Internal_Org_dep,
):
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
