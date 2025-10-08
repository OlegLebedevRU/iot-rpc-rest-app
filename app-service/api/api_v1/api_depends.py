import logging
from typing import Annotated
from fastapi import Header, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from core.models import db_helper

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
Org_dep = Annotated[int, Depends(org_id_dep)]
