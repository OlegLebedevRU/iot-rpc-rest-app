import logging.handlers
import httpx
from fastapi import HTTPException
from core import settings

log = logging.getLogger(__name__)
fh = logging.handlers.RotatingFileHandler(
    "/var/log/app/leo4_cloud.log",
    mode="a",
    maxBytes=10 * 1024 * 1024,
    backupCount=10,
    encoding=None,
)
fh.setLevel(logging.INFO)
formatter = logging.Formatter(settings.logging.log_format)
fh.setFormatter(formatter)
log.addHandler(fh)


async def get_token(api_key):
    r = httpx.get(
        url=str(settings.leo4.url) + "/api/login/",
        headers={"Authorization": "Bearer " + api_key},
    )
    log.info("login to leo4 cloud token %s = ", str(r.json()))

    if r is None:
        raise HTTPException(status_code=404, detail="Key not found")
    return r.json()


async def get_factory_device_list(api_key):
    r = httpx.get(
        url=str(settings.leo4.url) + "/api/login/",
        headers={"Authorization": "Bearer " + api_key},
    )
    log.info("login to leo4 cloud token %s = ", str(r.json()))

    if r is None:
        raise HTTPException(status_code=404, detail="Item not found")
    r1 = httpx.get(
        url=str(settings.leo4.url) + "/device/list/",
        headers={"accessToken": r.json()["accessToken"]},
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
