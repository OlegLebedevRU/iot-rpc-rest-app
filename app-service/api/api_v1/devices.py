import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, Request, Response

from sqlalchemy.ext.asyncio import AsyncSession

# from starlette.requests import Request

from api.api_v1.api_depends import Org_dep
from core import settings
from core.models import db_helper
from core.schemas.devices import DeviceTagPut, DeviceListResult
from core.services.devices import DeviceService

log = logging.getLogger(__name__)
router = APIRouter(
    prefix=settings.api.v1.devices,
    tags=["Devices"],
)


@router.get("/", description="Devices status", response_model=[DeviceListResult])
async def devices(
    session: Annotated[AsyncSession, Depends(db_helper.session_getter)],
    org_id: Org_dep,
    device_id: Annotated[int | None, Query()] = None,
):
    return await DeviceService.get_list(session, org_id, device_id)


@router.put("/{device_id}", description="Add Device tags")
async def add_device_tag(
    session: Annotated[AsyncSession, Depends(db_helper.session_getter)],
    org_id: Org_dep,
    device_id: int,
    device_tag: DeviceTagPut,
):
    tag_id = await DeviceService.proxy_upsert_tag(
        session, org_id, device_id, device_tag.tag, device_tag.value
    )
    return {"tag_id": tag_id}


@router.get("/certificates/")
async def legacy(
    function: Annotated[str, Query],
    pin: Annotated[str, Query],
    tosign: Annotated[str, Query],
    request: Request,
):
    # log.info("get certificates path = %s", path)
    log.info("get certificates req %s, %s", request.url, request.query_params)
    return Response(
        content="""<?xml version = "1.0" encoding = "windows-1251"?>
<Response>
    <Result>OK</Result>
    <code>0</code>
    <CERTDATA>
        <catype>SubCA</catype>
        <prov>Microsoft Enhanced Cryptographic Provider v1.0</prov>
        <dn>CN=34360826,O=509,OU=1003002,S=msk,C=ru,L=2913,E=1.terminal@forpay.ru</dn>
        <pin>J31AG2</pin>
        <sign>04C518FFE1B924CEB2F6A0BF2C73939D</sign>
    </CERTDATA>
</Response>
    """,
        media_type="application/xml",
    )


@router.post("/certificates/")
async def legacy1(
    function: Annotated[str, Query],
    pin: Annotated[str, Query],
    cpserial: Annotated[str, Query],
    request: Request,
):
    body = await request.body()

    log.info("post certificates %s", body)
    log.info("post certificates header %s", request.headers)
    return Response(
        media_type="application/xml",
        content="""<?xml version = "1.0" encoding = "windows-1251"?><Response><Result>OK</Result><code>0</code><CERTDATA>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
ntMthogBXjOtAXyT85oPUAKDdDEA
</CERTDATA></Response>""",
    )
