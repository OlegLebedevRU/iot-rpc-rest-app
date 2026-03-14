from core.logging_config import setup_module_logger
from typing import Annotated, Optional
from fastapi import Header, Depends, Security, HTTPException
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from core.config import settings
from core.models import db_helper

log = setup_module_logger(__name__, "api_depends.log")


async def org_id_dep(
    org_id: Annotated[
        int, Header(convert_underscores=False)
    ],  # Отключаем преобразование, т.к. заголовок с CamelCase
):
    log.info("header request, orgId=%s", org_id)
    return org_id


Session_dep = Annotated[
    AsyncSession,
    Depends(db_helper.session_getter),
]

# Схема получения API-ключа из заголовка (auto_error=False — чтобы перейти к проверке orgId при отсутствии ключа)
api_key_header = APIKeyHeader(name="x-api-key", auto_error=False)


# === Обновлённая зависимость: сначала x-api-key, потом orgId в заголовке ===
async def get_org_id_dependency(
    api_key: Optional[str] = Security(api_key_header),
    org_id: Optional[int] = Header(
        None, alias="orgId"
    ),  # Явно указываем имя заголовка как 'orgId'
) -> int:
    log.info(
        "Resolving org_id: api_key present=%s, orgId header=%s",
        api_key is not None,
        org_id,
    )

    # Попытка 1: через x-api-key
    if api_key:
        if api_key in settings.api_keys:
            org_id_from_key = settings.api_keys[api_key]
            log.info("Resolved org_id from API key: %s", org_id_from_key)
            return org_id_from_key
        else:
            log.warning("Invalid API key provided: %s", api_key)

    # Попытка 2: через заголовок orgId (CamelCase, без преобразования)
    if org_id is not None:
        log.info("Using org_id from 'orgId' header: %s", org_id)
        return org_id

    # Не удалось определить org_id
    log.error("Failed to resolve org_id: no valid api_key or orgId header")
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Invalid or missing API Key or required 'orgId' header",
    )


# Обновлённая универсальная зависимость
Org_dep = Annotated[int, Depends(get_org_id_dependency)]
