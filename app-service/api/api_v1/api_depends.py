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

# HTTP header for API key retrieval in public OpenAPI
api_key_header = APIKeyHeader(
    name="x-api-key",
    description="Organization API Key",
    auto_error=False,
)


async def get_org_id_dependency(
    request: Request,
    session: Session_dep,
    api_key: Optional[str] = Security(api_key_header),
) -> int:
    resolved_org_id: int | None = None

    # 1. Extract API key from x-api-key Security param or headers fallback (X-API-Key, Authorization: ApiKey/Bearer)
    raw_api_key = (
        api_key
        or request.headers.get("x-api-key")
        or request.headers.get("X-API-Key")
    )
    if not raw_api_key:
        auth_header = (request.headers.get("Authorization") or "").strip()
        if auth_header.startswith("ApiKey "):
            raw_api_key = auth_header[7:].strip()
        elif auth_header.startswith("Bearer "):
            cand_key = auth_header[7:].strip()
            # If Bearer token is a JWT (starts with eyJ or has 2 dots), do NOT treat as DB API key
            if not (cand_key.startswith("eyJ") or cand_key.count(".") == 2):
                raw_api_key = cand_key

    # 2. Validate API key against DB org_api_keys
    if raw_api_key:
        stmt = select(OrgApiKey.org_id).where(
            OrgApiKey.api_key == raw_api_key,
            OrgApiKey.is_active.is_(True),
        )
        db_org_id = await session.scalar(stmt)
        if db_org_id is not None:
            resolved_org_id = db_org_id
            log.info("Resolved org_id=%s from active DB API key", resolved_org_id)
        elif raw_api_key in settings.api_keys:
            resolved_org_id = settings.api_keys[raw_api_key]
            log.info("Resolved org_id=%s from static settings API key", resolved_org_id)
        else:
            log.warning(
                "Authentication failed: invalid or inactive API key: %s",
                raw_api_key[:12] if len(raw_api_key) > 12 else raw_api_key,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or inactive API Key",
            )

    # 3. If still unable to resolve org_id
    if resolved_org_id is None:
        log.warning("Authentication failed: missing API key or insufficient permissions")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authentication credentials (x-api-key required)",
        )

    # Store org_id on request.state for billing middleware
    request.state.billing_org_id = resolved_org_id
    return resolved_org_id


Org_dep = Annotated[int, Depends(get_org_id_dependency)]
