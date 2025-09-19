from core.integrations.rmq_admin_api import RmqAdminApi


class RmqAdmin:
    @classmethod
    def __init__(cls):
        pass

    @classmethod
    async def get_online_devices(cls, sn_arr):
        return await RmqAdminApi.get_connection(sn_arr)
