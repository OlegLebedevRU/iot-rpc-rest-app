from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.logging_config import setup_module_logger
from core.models import db_helper
from core.schemas.provisioning import (
    BatchTerminalProvisionRequest,
    BatchTerminalProvisionResponse,
    BatchTerminalStatusResponse,
    TerminalProvisionRequest,
    TerminalProvisionResult,
    TerminalStatusQuery,
)
from core.services.provisioning import ProvisioningService

log = setup_module_logger(__name__, "api_provisioning.log")

router = APIRouter(
    prefix=settings.api.v1.provisioning,
    tags=["Provisioning"],
)

service_key_header = APIKeyHeader(name="X-Internal-Service-Key", auto_error=False)
api_key_header = APIKeyHeader(name="x-api-key", auto_error=False)


async def verify_service_auth(
    internal_key: Optional[str] = Security(service_key_header),
    api_key: Optional[str] = Security(api_key_header),
    auth_header: Optional[str] = Header(None, alias="Authorization"),
) -> bool:
    """Verify service authorization using internal service token or valid API key."""
    configured_secret = (settings.auth.internal_service_key or "").strip()

    # 1. If configured internal secret is provided, check exact match
    if configured_secret:
        if internal_key and internal_key == configured_secret:
            return True
        if api_key and api_key == configured_secret:
            return True
        if auth_header and auth_header.replace("Bearer ", "").strip() == configured_secret:
            return True
        log.warning("Provisioning auth failed: invalid internal service key")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid internal service credentials",
        )

    # 2. Fallback: check if standard api_key is recognized
    if api_key and api_key in settings.api_keys:
        return True

    # 3. If no secrets configured at all (e.g. local dev), allow with warning
    if not settings.api_keys and not configured_secret:
        log.warning("Provisioning auth bypassed: no API keys or internal service key configured")
        return True

    log.warning("Provisioning auth failed: no valid credentials provided")
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Missing or invalid authentication credentials",
    )


Session_dep = Annotated[AsyncSession, Depends(db_helper.session_getter)]
Auth_dep = Annotated[bool, Depends(verify_service_auth)]


@router.post(
    "/terminals",
    description="Provision a single terminal into Leo4 IoT Platform and RabbitMQ",
    response_model=TerminalProvisionResult,
)
async def provision_single_terminal(
    request: TerminalProvisionRequest,
    session: Session_dep,
    _: Auth_dep,
) -> TerminalProvisionResult:
    results = await ProvisioningService.provision_terminals(session, [request])
    if not results:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to provision terminal",
        )
    return results[0]


@router.post(
    "/terminals/batch",
    description="Provision multiple terminals in batch into Leo4 IoT Platform and RabbitMQ",
    response_model=BatchTerminalProvisionResponse,
)
async def provision_batch_terminals(
    request: BatchTerminalProvisionRequest,
    session: Session_dep,
    _: Auth_dep,
) -> BatchTerminalProvisionResponse:
    results = await ProvisioningService.provision_terminals(session, request.terminals)
    return BatchTerminalProvisionResponse(results=results)


@router.post(
    "/terminals/status",
    description="Query provisioning and connection status for a list of device_ids",
    response_model=BatchTerminalStatusResponse,
)
async def get_terminals_status(
    query: TerminalStatusQuery,
    session: Session_dep,
    _: Auth_dep,
) -> BatchTerminalStatusResponse:
    statuses = await ProvisioningService.get_terminals_status(
        session, query.device_ids
    )
    return BatchTerminalStatusResponse(statuses=statuses)
