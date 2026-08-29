from __future__ import annotations

from typing import Annotated
from fastapi import Depends, HTTPException, Request
from starlette import status
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.logging_config import setup_module_logger
from core.models import db_helper

log = setup_module_logger(__name__, "internal_depends.log")

Session_dep = Annotated[
    AsyncSession,
    Depends(db_helper.session_getter),
]


async def verify_internal_service_auth(
    request: Request,
) -> bool:
    """Verify internal service authorization using X-Internal-Service-Key header or Bearer secret."""
    configured_secret = (settings.auth.internal_service_key or "").strip()

    internal_key = (
        request.headers.get("X-Internal-Service-Key")
        or request.headers.get("x-internal-service-key")
        or request.headers.get("X-Service-Key")
    )
    auth_header = (request.headers.get("Authorization") or "").strip()
    bearer_token = (
        auth_header[7:].strip() if auth_header.startswith("Bearer ") else None
    )

    # 1. If configured internal secret is provided, check exact match
    if configured_secret:
        if internal_key and internal_key == configured_secret:
            return True
        if bearer_token and bearer_token == configured_secret:
            return True
        # Fallback: check static api keys if matching
        if internal_key and internal_key in settings.api_keys:
            return True
        log.warning("Internal service auth failed: invalid internal service key")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid internal service credentials",
        )

    # 2. Fallback: check if standard api_key is recognized in static settings
    if internal_key and internal_key in settings.api_keys:
        return True

    # 3. If no secrets configured at all (e.g. local dev / test), allow with warning
    if not settings.api_keys and not configured_secret:
        log.warning(
            "Internal service auth bypassed: no API keys or internal service key configured"
        )
        return True

    log.warning("Internal service auth failed: no valid credentials provided")
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Missing or invalid authentication credentials",
    )


Internal_Auth_dep = Annotated[bool, Depends(verify_internal_service_auth)]


async def get_internal_org_id(
    request: Request,
    _: Internal_Auth_dep,
) -> int:
    """Extract target tenant org_id from X-Org-Id header or org_id query parameter."""
    org_id_header = (
        request.headers.get("X-Org-Id")
        or request.headers.get("x-org-id")
        or request.headers.get("orgId")
        or request.headers.get("jwt-org")
    )
    org_id_query = request.query_params.get("org_id")

    raw_org_id = org_id_header or org_id_query
    if raw_org_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required 'X-Org-Id' header for internal service request",
        )
    try:
        org_id = int(raw_org_id)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid 'X-Org-Id' header: must be a valid integer",
        )

    request.state.billing_org_id = org_id
    return org_id


Internal_Org_dep = Annotated[int, Depends(get_internal_org_id)]


async def get_internal_billing_org_id(
    request: Request,
    _: Internal_Auth_dep,
) -> int:
    """Extract org_id for internal billing operations, defaulting to 0 (admin)."""
    org_id_header = (
        request.headers.get("X-Org-Id")
        or request.headers.get("x-org-id")
        or request.headers.get("orgId")
    )
    org_id_query = request.query_params.get("org_id")
    raw_org_id = org_id_header or org_id_query
    if raw_org_id is not None:
        try:
            org_id = int(raw_org_id)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid 'X-Org-Id' header: must be a valid integer",
            )
    else:
        org_id = 0
    request.state.billing_org_id = org_id
    return org_id


Internal_Billing_Org_dep = Annotated[int, Depends(get_internal_billing_org_id)]
