from collections.abc import Awaitable, Callable, Iterable
from datetime import date
from typing import TypeVar

from fastapi import HTTPException
from starlette import status

T = TypeVar("T")


def require_billing_admin(org_id: int) -> None:
    """Raise 403 if org_id is not the billing admin org."""
    if org_id != 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Billing admin endpoints are only accessible for org_id=0",
        )


def coefficient_change_affects_period(
    effective_from: date,
    period_start: date,
    current_effective_from: date | None,
) -> bool:
    """Return True when a coefficient change would alter the given billing period."""
    if effective_from > period_start:
        return False
    if current_effective_from is None:
        return True
    return effective_from >= current_effective_from


def evt_billing_counter_type(
    event_type_code: int,
    gauge_event_types: Iterable[int],
) -> str:
    """Resolve EVT billing counter type according to billing rules."""
    return "evt" if event_type_code != 0 and event_type_code not in gauge_event_types else "activity"


async def publish_then_process(
    publish: Callable[[], Awaitable[None]],
    process: Callable[[], Awaitable[T]],
) -> T:
    """Publish billing activity before executing the main message processing."""
    await publish()
    return await process()
