import logging
from typing import Annotated
from fastapi import Header, Depends, Security, HTTPException
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from core.config import settings
from core.models import db_helper

# === Отладка: распечатайте, что загружено ===

log = logging.getLogger(__name__)


async def org_id_dep(
    orgId: Annotated[int, Header(convert_underscores=True)],
):
    log.info("header request, org-id=%s", orgId)
    return orgId


Session_dep = Annotated[
    AsyncSession,
    Depends(db_helper.session_getter),
]
# Org_dep = Annotated[int, Depends(org_id_dep)]
# === Схема получения API-ключа из заголовка ===
api_key_header = APIKeyHeader(name="x-api-key", auto_error=True)


# === Зависимость для получения org_id по API-ключу ===
async def get_org_id_from_api_key(api_key: str = Security(api_key_header)) -> int:
    if api_key not in settings.api_keys:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid or missing API Key"
        )
    return settings.api_keys[api_key]


# Зависимость для внедрения org_id
Org_dep = Annotated[int, Depends(get_org_id_from_api_key)]
