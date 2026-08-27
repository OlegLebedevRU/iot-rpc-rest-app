from __future__ import annotations

from typing import Annotated, Optional
from fastapi import Header, Depends, Query, Security, HTTPException, Request
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from starlette import status

from core.config import settings
from core.logging_config import setup_module_logger
from core.models import db_helper, OrgApiKey

log = setup_module_logger(__name__, "api_depends.log")

Session_dep = Annotated[
    AsyncSession,
    Depends(db_helper.session_getter),
]

# HTTP headers for API key retrieval
api_key_header = APIKeyHeader(name="x-api-key", auto_error=False)
api_key_header_alt = APIKeyHeader(name="X-API-Key", auto_error=False)
internal_service_key_header = APIKeyHeader(name="X-Internal-Service-Key", auto_error=False)


async def get_org_id_dependency(
    request: Request,
    session: Session_dep,
    api_key_lower: Optional[str] = Security(api_key_header),
    api_key_upper: Optional[str] = Security(api_key_header_alt),
    internal_service_key: Optional[str] = Security(internal_service_key_header),
    auth_header: Optional[str] = Header(None, alias="Authorization"),
    org_id_str: Optional[str] = Header(None, alias="orgId"),
    x_org_id_str: Optional[str] = Header(None, alias="X-Org-Id"),
    role_header: Optional[str] = Header(None, alias="X-Role"),
    role_id_header: Optional[str] = Header(None, alias="X-Role-Id"),
    jwt_role_header: Optional[str] = Header(None, alias="jwt-role"),
    org_id_query: Optional[int] = Query(None, alias="org_id"),
) -> int:
    resolved_org_id: int | None = None

    # 1. Extract API key from headers (X-API-Key, x-api-key, Authorization: ApiKey <key> / Bearer <key>)
    raw_api_key = api_key_upper or api_key_lower
    if not raw_api_key and auth_header:
        auth_clean = auth_header.strip()
        if auth_clean.startswith("ApiKey "):
            raw_api_key = auth_clean[7:].strip()
        elif auth_clean.startswith("Bearer "):
            raw_api_key = auth_clean[7:].strip()

    # Check internal service key (X-Internal-Service-Key or passed as API key)
    configured_internal_secret = (settings.auth.internal_service_key or "").strip()
    is_internal_call = False
    if configured_internal_secret:
        if internal_service_key and internal_service_key == configured_internal_secret:
            is_internal_call = True
        elif raw_api_key and raw_api_key == configured_internal_secret:
            is_internal_call = True

    if is_internal_call:
        if org_id_query is not None:
            resolved_org_id = org_id_query
        elif org_id_str is not None:
            try:
                resolved_org_id = int(org_id_str)
            except (ValueError, TypeError):
                pass
        elif x_org_id_str is not None:
            try:
                resolved_org_id = int(x_org_id_str)
            except (ValueError, TypeError):
                pass
        if resolved_org_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing required 'org_id' parameter or header for internal service request",
            )
        request.state.billing_org_id = resolved_org_id
        return resolved_org_id

    # 2. If API key was provided -> validate against DB tb_org_api_keys
    if raw_api_key:
        stmt = select(OrgApiKey.org_id).where(
            OrgApiKey.api_key == raw_api_key,
            OrgApiKey.is_active.is_(True),
        )
        db_org_id = await session.scalar(stmt)
        if db_org_id is not None:
            resolved_org_id = db_org_id
            log.info("Resolved org_id=%s from active DB API key", resolved_org_id)
        else:
            log.warning("Authentication failed: invalid or inactive API key: %s", raw_api_key)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or inactive API Key",
            )

    # 3. Fallback to trusted web headers from Nginx (MenuBuilder superuser)
    if resolved_org_id is None:
        role = str(role_header or jwt_role_header or "").lower()
        role_id = str(role_id_header or "").lower()
        user_id = str(
            request.headers.get("X-User-Id")
            or request.headers.get("jwt-sub")
            or request.headers.get("sub")
            or ""
        )

        is_superuser = (
            role in ("superuser", "admin", "1")
            or role_id in ("1", "superuser", "admin")
            or user_id == "1"
        )

        if is_superuser:
            if org_id_query is not None:
                resolved_org_id = org_id_query
            else:
                effective_org_id_str = (
                    org_id_str
                    or x_org_id_str
                    or request.headers.get("jwt-org")
                    or request.headers.get("org")
                    or request.headers.get("orgid")
                )
                if effective_org_id_str is not None:
                    try:
                        resolved_org_id = int(effective_org_id_str)
                    except (ValueError, TypeError):
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Invalid 'orgId' header: must be a valid integer",
                        )

    # 4. If still unable to resolve org_id
    if resolved_org_id is None:
        log.warning("Authentication failed: missing API key or insufficient permissions")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authentication credentials",
        )

    # Store org_id on request.state for billing middleware
    request.state.billing_org_id = resolved_org_id
    return resolved_org_id


Org_dep = Annotated[int, Depends(get_org_id_dependency)]
