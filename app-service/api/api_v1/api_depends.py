from core.logging_config import setup_module_logger
from typing import Annotated, Optional
from fastapi import Header, Depends, Security, HTTPException
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


# === Обновлённая зависимость: сначала x-api-key, потом orgId в заголовке ===
async def get_org_id_dependency(
    api_key: Optional[str] = Security(api_key_header),
    org_id_str: Optional[str] = Header(
        None, alias="orgId"
    ),  # Получаем orgId как строку
) -> int:
    log.info(
        "Resolving org_id: api_key present=%s, orgId header=%s",
        api_key is not None,
        org_id_str,
    )

    # Попытка 1: через x-api-key
    if api_key:
        if api_key in settings.api_keys:
            org_id_from_key = settings.api_keys[api_key]
            log.info("Resolved org_id from API key: %s", org_id_from_key)
            return org_id_from_key
        else:
            log.warning("Invalid API key provided: %s", api_key)

    # Попытка 2: через заголовок orgId (как строка, которую нужно преобразовать)
    if org_id_str is not None:
        try:
            org_id = int(org_id_str)
            log.info("Successfully parsed orgId header as int: %s", org_id)
            return org_id
        except ValueError, TypeError:
            log.error("Invalid orgId format in header: %s (not a number)", org_id_str)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid 'orgId' header: must be a valid integer",
            )

    # Не удалось определить org_id
    log.error("Failed to resolve org_id: no valid api_key or orgId header")
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Invalid or missing API Key or required 'orgId' header",
    )


# Обновлённая универсальная зависимость
Org_dep = Annotated[int, Depends(get_org_id_dependency)]
