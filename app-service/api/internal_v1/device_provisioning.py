from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Response, status

from api.internal_v1.internal_depends import Internal_Auth_dep, Session_dep
from core.logging_config import setup_module_logger
from core.schemas.device_provisioning import (
    DeviceProvisionErrorResponse,
    DeviceProvisionRequest,
    DeviceProvisionResponse,
    DeviceProvisionStatus,
)
from core.services.device_provisioning_service import device_provisioning_service

log = setup_module_logger(__name__, "api_internal_device_provisioning.log")

router = APIRouter(
    prefix="/devices/provision",
    tags=["Internal Device Provisioning"],
)


def _build_response(record: Any, is_replayed: bool) -> DeviceProvisionResponse:
    return DeviceProvisionResponse(
        operation_id=record.operation_id,
        status=DeviceProvisionStatus(record.status),
        tenant_id=record.tenant_id,
        terminal_id=record.terminal_id,
        device_id=record.device_id,
        sn=record.sn,
        contract_version=record.contract_version,
        correlation_id=record.correlation_id,
        replayed_flag=is_replayed,
        created_at=record.created_at,
        provisioned_at=record.provisioned_at,
        error_code=record.error_code,
        error_message=record.error_message,
    )


@router.post(
    "",
    response_model=DeviceProvisionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Provision a device and terminal idempotently",
    description=(
        "Versioned idempotent device provisioning. Replay of identical operation_id "
        "returns HTTP 200 with replayed_flag=True. Reused operation_id with differing "
        "parameters or conflicting identity returns HTTP 409 Conflict."
    ),
    responses={
        201: {"description": "Device successfully provisioned", "model": DeviceProvisionResponse},
        200: {"description": "Idempotent replay of previously completed provisioning", "model": DeviceProvisionResponse},
        400: {"description": "Invalid payload or validation failure", "model": DeviceProvisionErrorResponse},
        401: {"description": "Unauthorized / authentication credentials missing"},
        403: {"description": "Forbidden / invalid service key"},
        409: {"description": "Operation ID conflict or identity/tenant mismatch", "model": DeviceProvisionErrorResponse},
    },
)
@router.post(
    "/",
    response_model=DeviceProvisionResponse,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
async def provision_device(
    data: DeviceProvisionRequest,
    session: Session_dep,
    _: Internal_Auth_dep,
    response: Response,
) -> DeviceProvisionResponse:
    rec, is_replayed = await device_provisioning_service.provision_device(session, data)
    await session.commit()
    await session.refresh(rec)

    if is_replayed:
        response.status_code = status.HTTP_200_OK

    return _build_response(rec, is_replayed)


@router.get(
    "/by-operation/{operation_id}",
    response_model=DeviceProvisionResponse,
    summary="Get provisioning record by operation_id",
    responses={
        200: {"description": "Provisioning record found", "model": DeviceProvisionResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "Forbidden"},
        404: {"description": "Operation ID not found", "model": DeviceProvisionErrorResponse},
    },
)
async def get_provisioning_by_operation(
    operation_id: str,
    session: Session_dep,
    _: Internal_Auth_dep,
) -> DeviceProvisionResponse:
    rec = await device_provisioning_service.get_provisioning_by_operation(session, operation_id)
    if rec is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "OPERATION_NOT_FOUND",
                "message": f"Provisioning operation '{operation_id}' not found",
                "operation_id": operation_id,
            },
        )
    return _build_response(rec, is_replayed=True)


@router.get(
    "/by-sn/{sn}",
    response_model=DeviceProvisionResponse,
    summary="Get latest provisioning record by device SN",
    responses={
        200: {"description": "Provisioning record found", "model": DeviceProvisionResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "Forbidden"},
        404: {"description": "Device SN not found", "model": DeviceProvisionErrorResponse},
    },
)
async def get_provisioning_by_sn(
    sn: str,
    session: Session_dep,
    _: Internal_Auth_dep,
) -> DeviceProvisionResponse:
    rec = await device_provisioning_service.get_provisioning_by_sn(session, sn)
    if rec is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "DEVICE_NOT_FOUND",
                "message": f"Device with SN '{sn}' is not provisioned",
            },
        )
    return _build_response(rec, is_replayed=True)


@router.get(
    "/{operation_id}",
    response_model=DeviceProvisionResponse,
    summary="Get provisioning record by operation_id (direct path)",
    include_in_schema=False,
)
async def get_provisioning_by_operation_direct(
    operation_id: str,
    session: Session_dep,
    auth: Internal_Auth_dep,
) -> DeviceProvisionResponse:
    return await get_provisioning_by_operation(operation_id, session, auth)
