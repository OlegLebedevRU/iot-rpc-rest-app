from core.logging_config import setup_module_logger
from typing import Annotated, Optional
from fastapi import Header, Depends, Query, Security, HTTPException, Request
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from core.config import settings
from core.models import db_helper

log = setup_module_logger(__name__, "api_depends.log")

Session_dep = Annotated[
    AsyncSession,
    Depends(db_helper.session_getter),
]

# Схема получения API-ключа из заголовка (auto_error=False — чтобы перейти к проверке orgId при отсутствии ключа)
api_key_header = APIKeyHeader(name="x-api-key", auto_error=False)


# === Обновлённая зависимость: x-api-key или проверка суперадмина + org_id ===
async def get_org_id_dependency(
    request: Request,
    api_key: Optional[str] = Security(api_key_header),
    org_id_str: Optional[str] = Header(None, alias="orgId"),
    x_org_id_str: Optional[str] = Header(None, alias="X-Org-Id"),
    role_header: Optional[str] = Header(None, alias="X-Role"),
    role_id_header: Optional[str] = Header(None, alias="X-Role-Id"),
    jwt_role_header: Optional[str] = Header(None, alias="jwt-role"),
    org_id_query: Optional[int] = Query(None, alias="org_id"),
) -> int:
    resolved_org_id: int | None = None

    # Попытка 1: через x-api-key
    if api_key:
        if api_key in settings.api_keys:
            resolved_org_id = settings.api_keys[api_key]
            log.info("Resolved org_id from API key: %s", resolved_org_id)
        elif (
            hasattr(settings, "auth")
            and hasattr(settings.auth, "internal_service_key")
            and settings.auth.internal_service_key
            and api_key == settings.auth.internal_service_key
        ):
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
        else:
            log.warning("Invalid API key provided: %s", api_key)

    # Попытка 2: через веб-заголовки от Nginx
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

        if not is_superuser:
            log.error(
                "Access denied: only superusers can access management endpoints (role=%s, role_id=%s, user_id=%s)",
                role,
                role_id,
                user_id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: Management functionality is restricted to superusers only",
            )

        # Для суперадмина: приоритет у query параметра org_id, затем у заголовка
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

    # Не удалось определить org_id
    if resolved_org_id is None:
        log.error("Failed to resolve org_id: no valid api_key or org_id parameter/header")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required 'org_id' parameter or header",
        )

    # Store org_id on request.state for billing middleware
    request.state.billing_org_id = resolved_org_id
    return resolved_org_id


# Обновлённая универсальная зависимость
Org_dep = Annotated[int, Depends(get_org_id_dependency)]
