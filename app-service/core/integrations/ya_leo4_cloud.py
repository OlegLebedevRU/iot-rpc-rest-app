import logging
import httpx
from fastapi import HTTPException
from core import settings

log = logging.getLogger(__name__)


async def get_token(api_key):
    r = httpx.get(
        url=str(settings.leo4.url) + "account/login2",
        headers={"Authorization": "Bearer " + api_key},
    )
    log.info("login to leo4 cloud token %s = ", str(r.json()))

    if r is None:
        raise HTTPException(status_code=404, detail="Key not found")
    return r.json()


async def get_factory_device_list(api_key):
    r = httpx.get(
        url=str(settings.leo4.url) + "account/login2",
        headers={"Authorization": "Bearer " + api_key},
    )
    log.info("login to leo4 cloud token %s = ", str(r.json()))

    if r is None:
        raise HTTPException(status_code=404, detail="Item not found")
    r1 = httpx.get(
        url=str(settings.leo4.url) + "device/list",
        headers={"Authorization": "Bearer " + r.json()["accessToken"]},
    )
    # -------------------------------------------------
    if r1.status_code == 403:
        raise HTTPException(status_code=403, detail="Leo4 cloud auth error")
    if r1.status_code == 500:
        log.info("error from cloud device list %s = ", r1.json())
        raise HTTPException(status_code=500, detail="Leo4 cloud 500 error")

    da = r1.json()
    if da:
        log.info("from cloud device list %s = ", str(da[0]))
    return da
