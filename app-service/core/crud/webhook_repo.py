import httpx
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func
from core.models.webhook import OrgWebhook
from core.logging_config import setup_module_logger
from core.config import settings

log = setup_module_logger(__name__, "webhook_repo.log")


class WebhookRepo:
    """ "
    ✅ Пример данных в таблице org_webhooks
    id
    org_id
    event_type
    url
    headers
    1
    100
    msg-event
    https://api.client.com/webhook
    {"Authorization": "..."}
    2
    100
    msg-task-result
    https://api.client.com/task-result
    {"X-API-Key": "123"}
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_org_and_type(
        self, org_id: int, event_type: str
    ) -> Optional[OrgWebhook]:
        result = await self.session.execute(
            select(OrgWebhook).where(
                OrgWebhook.org_id == org_id, OrgWebhook.event_type == event_type
            )
        )
        return result.scalar_one_or_none()

    async def get_all_by_org(self, org_id: int) -> List[OrgWebhook]:
        result = await self.session.execute(
            select(OrgWebhook).where(OrgWebhook.org_id == org_id)
        )
        return list(result.scalars().all())

    async def count_by_org(self, org_id: int) -> int:
        result = await self.session.execute(
            select(func.count(OrgWebhook.id)).where(OrgWebhook.org_id == org_id)
        )
        return result.scalar_one()

    async def create_or_update(
        self,
        org_id: int,
        event_type: str,
        url: str,
        headers: dict = None,
        is_active: bool = True,
    ) -> OrgWebhook:
        # Проверка лимита
        current_count = await self.count_by_org(org_id)
        if current_count >= settings.webhook.max_per_org:
            raise ValueError(
                f"Webhook limit reached: max {settings.webhook.max_per_org} per org"
            )

        # Проверка доступности URL
        if is_active:
            try:
                async with httpx.AsyncClient(
                    timeout=settings.webhook.timeout
                ) as client:
                    resp = await client.get(str(url), headers=headers)
                    if resp.status_code >= 400:
                        log.warning(
                            "Webhook URL returned error %d: %s", resp.status_code, url
                        )
            except Exception as e:
                log.error("Failed to reach webhook URL %s: %s", url, str(e))
                raise ValueError(f"Cannot reach webhook URL: {str(e)}")

        webhook = await self.get_by_org_and_type(org_id, event_type)
        if webhook:
            await self.session.execute(
                update(OrgWebhook)
                .where(OrgWebhook.id == webhook.id)
                .values(url=url, headers=headers, is_active=is_active)
            )
            await self.session.refresh(webhook)
            return webhook
        else:
            new_webhook = OrgWebhook(
                org_id=org_id,
                event_type=event_type,
                url=url,
                headers=headers,
                is_active=is_active,
            )
            self.session.add(new_webhook)
            await self.session.flush()
            return new_webhook

    async def delete(self, org_id: int, event_type: str) -> bool:
        webhook = await self.get_by_org_and_type(org_id, event_type)
        if not webhook:
            return False
        await self.session.delete(webhook)
        return True
