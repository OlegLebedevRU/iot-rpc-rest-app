from typing import Annotated
from fastapi import Header, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from core.models import db_helper


async def org_id_dep(
    org_id: Annotated[int, Header()],
):
    return org_id


Session_dep = Annotated[
    AsyncSession,
    Depends(db_helper.session_getter),
]
Org_dep = Annotated[int, Depends(org_id_dep)]
