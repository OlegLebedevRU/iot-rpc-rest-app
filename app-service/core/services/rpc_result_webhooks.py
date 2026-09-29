"""Bounded, restart-safe HTTP delivery of RPC results stored in PostgreSQL."""

import asyncio
import logging
from datetime import timedelta

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core import settings
from core.integrations.webhooks import (
    Webhook,
    WebhookConfig,
    is_retryable_webhook_error,
)
from core.models import db_helper
from core.models.device_tasks import DevTask, DevTaskResult, RpcResultWebhook
from core.models.webhook import OrgWebhook

log = logging.getLogger(__name__)
RETRY_DELAYS = (5, 15, 45, 120, 300)


async def deliver_one(session: AsyncSession) -> bool:
    """Caller commits the attempt. Only the delivery row is locked during HTTP."""
    row = (
        await session.execute(
            select(
                RpcResultWebhook,
                DevTaskResult,
                DevTask,
                OrgWebhook,
                func.clock_timestamp(),
            )
            .join(DevTaskResult, DevTaskResult.id == RpcResultWebhook.result_id)
            .join(DevTask, DevTask.id == DevTaskResult.task_id)
            .join(OrgWebhook, OrgWebhook.id == RpcResultWebhook.webhook_id)
            .where(
                RpcResultWebhook.finished_at.is_(None),
                RpcResultWebhook.next_attempt_at <= func.clock_timestamp(),
            )
            .order_by(RpcResultWebhook.next_attempt_at, RpcResultWebhook.result_id)
            .limit(1)
            .with_for_update(of=RpcResultWebhook, skip_locked=True)
        )
    ).one_or_none()
    if row is None:
        return False
    delivery, result, task, webhook, now = row
    if now >= delivery.expires_at or not webhook.is_active:
        delivery.finished_at = now
        delivery.last_error = "expired" if now >= delivery.expires_at else "disabled"
        log.warning(
            "RPC webhook finished result_id=%s reason=%s",
            result.id,
            delivery.last_error,
        )
        return True

    headers = dict(webhook.headers or {})
    headers.update(
        {
            "x-msg-type": "msg-task-result",
            "x-device-id": str(task.device_id),
            "x-ext-id": str(result.ext_id),
            "x-result-id": str(result.id),
            "x-status-code": str(result.status_code),
        }
    )
    delivery.attempts += 1
    timeout = max(1.0, min(settings.webhook.timeout, 30.0))
    try:
        # Persisted scheduling owns retries; do not multiply them inside the client.
        async with asyncio.timeout(timeout):
            async with Webhook(
                url=webhook.url,
                path_suffix=f"/{task.id}",
                headers=headers,
                config=WebhookConfig(timeout=timeout, max_retries=0),
            ) as client:
                await client.send(result.result)
    except Exception as exc:
        delivery.last_error = (
            f"http_{exc.response.status_code}"
            if isinstance(exc, httpx.HTTPStatusError)
            else type(exc).__name__[:64]
        )
        if is_retryable_webhook_error(exc) and delivery.attempts <= len(RETRY_DELAYS):
            delivery.next_attempt_at = min(
                now + timedelta(seconds=RETRY_DELAYS[delivery.attempts - 1]),
                delivery.expires_at,
            )
        else:
            delivery.finished_at = now
        log.warning(
            "RPC webhook failed result_id=%s org_id=%s attempt=%s error=%s terminal=%s",
            result.id,
            webhook.org_id,
            delivery.attempts,
            delivery.last_error,
            delivery.finished_at is not None,
        )
    else:
        delivery.finished_at = now
        delivery.last_error = None
        log.info(
            "RPC webhook delivered result_id=%s org_id=%s attempt=%s",
            result.id,
            webhook.org_id,
            delivery.attempts,
        )
    return True


async def delivery_loop() -> None:
    while True:
        try:
            for _ in range(20):
                async with db_helper.session_factory() as session:
                    async with session.begin():
                        if not await deliver_one(session):
                            break
        except Exception as exc:
            # Never include exception text: HTTP errors can contain credentials in URLs.
            log.error("RPC webhook worker failed: %s", type(exc).__name__)
        await asyncio.sleep(1)
