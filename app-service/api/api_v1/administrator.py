import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, not_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from core import settings
from core.crud.dev_tasks_repo import TasksRepository
from core.models import db_helper, Device
import httpx

from core.models.devices import DeviceOrgBind
from core.models.orgs import Org

log = logging.getLogger(__name__)
router = APIRouter(
    prefix=settings.api.v1.admin,
    tags=["Administrator"],
)


@router.post(
    "/",
    description="Server admin",
)
async def do_admin(
    session: Annotated[AsyncSession, Depends(db_helper.session_getter)],
    action: str | None,
):  # TaskResponseStatus:
    if action == "get_d":
        r = httpx.get(
            url=str(settings.leo4.url) + "/account/login2",
            headers={"Authorization": "Bearer " + settings.leo4.api_key},
        )
        logging.info("token %s = ", str(r.json()))

        if r is None:
            raise HTTPException(status_code=404, detail="Item not found")
        r1 = httpx.get(
            url=str(settings.leo4.url) + "/device/list",
            headers={"Authorization": "Bearer " + r.json()["accessToken"]},
        )
        da = r1.json()
        logging.info("device list %s = ", str(da[0]))
        insert_stmt = (
            insert(Device)
            .values(
                [
                    {"device_id": int(d["device_id"]), "sn": d["serial_number"]}
                    for d in da
                ]
                # device_id=21,
                # sn="a1b21c22589d100424",
            )
            .on_conflict_do_nothing()
        )
        # , set_=dict(is_deleted=False

        await session.execute(insert_stmt)
        await session.commit()
        # print(do_nothing_stmt)
        return da
    elif action == "get_u":
        r = httpx.get(url=str(settings.leo4.admin_url) + "api/users")
        logging.info(f"resp <dev.{r}.ack>, body = {str(r)}")
        names = [""]
        n_obj = r.json()
        print(n_obj)
        for u in n_obj:
            names.append(u["name"])
        lu_q = select(Device.sn).where(not_(Device.sn.in_(names)))
        lu = await session.execute(lu_q)
        lu1 = lu.mappings().all()
        print(lu1)
        # defns = {"users": [], "permissions": []}
        d_users = []
        d_perm = []
        d_topic_perm = []
        for d in lu1:
            d_users.append(
                {
                    "name": d.sn,
                    "password_hash": "",
                    "hashing_algorithm": "rabbit_password_hashing_sha256",
                    "tags": ["device"],
                    "limits": {},
                }
            )
            d_perm.append(
                {
                    "user": d.sn,
                    "vhost": "/",
                    "configure": ".*",
                    "write": ".*",
                    "read": ".*",
                }
            )
            d_topic_perm.append(
                {
                    "user": d.sn,
                    "vhost": "/",
                    "exchange": "amq.topic",
                    "write": "^dev.{client_id}.*",
                    "read": "^srv.{client_id}.*",
                }
            )
        defns = {}
        defns["users"] = d_users
        defns["permissions"] = d_perm
        defns["topic_permissions"] = d_topic_perm
        print(defns)

        r = httpx.post(
            url=str(settings.leo4.admin_url) + "api/definitions",
            json=defns,
            headers={"Content-type": "application/json"},
        )
        print(r.status_code)

    # elif action == "test":
    #     insert_stmt = insert(Org).values(org_id=0)
    #     insert_bind = insert(DeviceOrgBind).values(org_id=0, device_id=4617)
    #     await session.execute(insert_stmt)
    #     await session.execute(insert_bind)
    #     await session.commit()
