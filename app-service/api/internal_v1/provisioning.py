from typing import Annotated

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.internal_v1.internal_depends import Internal_Auth_dep, Session_dep
from core.config import settings
from core.logging_config import setup_module_logger
from core.schemas.provisioning import (
    BatchTerminalProvisionRequest,
    BatchTerminalProvisionResponse,
    BatchTerminalStatusResponse,
    OrgApiKeyProvisionRequest,
    OrgApiKeyResponse,
    TerminalProvisionRequest,
    TerminalProvisionResult,
    TerminalStatusQuery,
)
from core.services.provisioning import ProvisioningService

log = setup_module_logger(__name__, "api_internal_provisioning.log")

router = APIRouter(
    prefix=settings.api.internal_v1.provisioning,
    tags=["Internal Provisioning"],
    include_in_schema=False,
)


@router.post(
    "/terminals",
    description="Provision a single terminal into Leo4 IoT Platform and RabbitMQ",
    response_model=TerminalProvisionResult,
)
async def provision_single_terminal(
    request: TerminalProvisionRequest,
    session: Session_dep,
    _: Internal_Auth_dep,
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
    _: Internal_Auth_dep,
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
    _: Internal_Auth_dep,
) -> BatchTerminalStatusResponse:
    statuses = await ProvisioningService.get_terminals_status(
        session, query.device_ids
    )
    return BatchTerminalStatusResponse(statuses=statuses)


@router.post(
    "/api-keys",
    description="Provision or update API key for an organization",
    response_model=OrgApiKeyResponse,
)
async def provision_org_api_key(
    request: OrgApiKeyProvisionRequest,
    session: Session_dep,
    _: Internal_Auth_dep,
) -> OrgApiKeyResponse:
    return await ProvisioningService.provision_org_api_key(session, request)


@router.get(
    "/api-keys/{org_id}",
    description="Get API key details for an organization (with optional masking)",
    response_model=OrgApiKeyResponse,
)
async def get_org_api_key(
    org_id: int,
    session: Session_dep,
    _: Internal_Auth_dep,
    mask: bool = False,
) -> OrgApiKeyResponse:
    result = await ProvisioningService.get_org_api_key(session, org_id, mask=mask)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"API key for organization {org_id} not found",
        )
    return result


@router.delete(
    "/api-keys/{org_id}",
    description="Delete API key for an organization",
    response_model=dict,
)
async def delete_org_api_key(
    org_id: int,
    session: Session_dep,
    _: Internal_Auth_dep,
) -> dict:
    deleted = await ProvisioningService.delete_org_api_key(session, org_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"API key for organization {org_id} not found",
        )
    return {"status": "deleted", "org_id": org_id}
