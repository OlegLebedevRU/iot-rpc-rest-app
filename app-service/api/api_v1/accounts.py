import logging

from fastapi import APIRouter

from api.api_v1.api_depends import Org_dep
from core import settings

log = logging.getLogger(__name__)
router = APIRouter(
    prefix=settings.api.v1.accounts,
    tags=["Accounts"],
)


@router.get(
    "/",
    description="Account status",
)
async def accounts(
    org_id: Org_dep,
):
    return {"org_id": org_id}
