import logging
import httpx
from fastapi import HTTPException
from core import settings

log = logging.getLogger(__name__)


async def get_factory_device_list(api_key):
    r = httpx.get(
        url=str(settings.leo4.url) + "/account/login2",
        headers={"Authorization": "Bearer " + api_key},
    )
    log.info("login to leo4 cloud token %s = ", str(r.json()))

    if r is None:
        raise HTTPException(status_code=404, detail="Item not found")
    r1 = httpx.get(
        url=str(settings.leo4.url) + "/device/list",
        headers={"Authorization": "Bearer " + r.json()["accessToken"]},
    )
    # -------------------------------------------------
    da = r1.json()
    log.info("from cloud device list %s = ", str(da[0]))
