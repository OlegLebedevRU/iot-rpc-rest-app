import logging
from uuid import UUID

from core.config import RoutingKey, settings
from core.logging_config import setup_module_logger
from core.schemas.device_tasks import TaskCreate, TaskResponse, TaskNotify
from core.schemas.rmq_admin import RmqClientsAction
from core.topologys.declare import (
    # topic_exchange,
    topic_publisher,
    job_publisher,
    direct_exchange,
)

log = setup_module_logger(__name__, "srv_dev_task_processing.log")
logging.getLogger("logger_proxy").setLevel(logging.WARNING)
topology = settings.rmq


async def send_tsk(sn: str, task: TaskCreate, stask: TaskResponse):

    task_device_topic = str(
        RoutingKey(settings.rmq.prefix_srv, sn, settings.rmq.suffix_task)
    )
    notify: TaskNotify = TaskNotify(
        id=stask.id, created_at=stask.created_at, header=task
    )
    await topic_publisher.publish(
        routing_key=task_device_topic,  # "srv.a3b0000000c99999d250813.tsk",
        message=notify,
        # exchange=topic_exchange,  # settings.rmq.x_name,
        correlation_id=stask.id,
        expiration=task.ttl * 60_000,
        headers={
            "method_code": str(notify.header.method_code),
            "correlationData": str(stask.id),
        },
    )


async def send_rsp(
    sn: str, t_resp: str, correlation_id: UUID | str, expiration: int, method_code: str
):
    routing_key: str = str(
        RoutingKey(prefix=topology.prefix_srv, sn=sn, suffix=topology.suffix_response)
    )
    await topic_publisher.publish(
        routing_key=routing_key,
        message=t_resp,
        correlation_id=correlation_id,  # str(correlation_id),uuid.UUID(correlation_id).bytes,
        # exchange=topic_exchange,  # settings.rmq.x_name,
        expiration=expiration,
        headers={
            "method_code": method_code,
            "correlationData": str(correlation_id),
        },
    )


async def send_cmt(
    sn: str,
    rmsg: str,
    msg: str,
    corr_id: UUID | str,
    dev_id: int,
    result_id: int,
    ext_id: int,
    status_code: int,
):

    routing_key: str = str(
        RoutingKey(prefix=topology.prefix_srv, sn=sn, suffix=topology.suffix_commited)
    )
    await topic_publisher.publish(
        routing_key=routing_key,
        message=rmsg,
        correlation_id=corr_id,
        # exchange=topic_exchange,  # settings.rmq.x_name,
        expiration=180 * 60_000,
        headers={
            "ext_id": str(ext_id),
            "result_id": str(result_id),
            "correlationData": str(corr_id),
        },
    )

    await topic_publisher.publish(
        routing_key=settings.webhook.webhooks_queue,  # "srv.a3b0000000c99999d250813.tsk",
        message=msg,
        exchange=direct_exchange,  # settings.rmq.x_name_direct,
        correlation_id=corr_id,
        expiration=30 * 60_000,
        headers={
            "x-device-id": str(dev_id),
            "x-msg-type": "msg-task-result",
            "x-ext-id": str(ext_id),
            "x-result-id": str(result_id),
            "x-status-code": str(status_code),
        },
    )


async def act_ttl(step: int):
    await job_publisher.publish(
        message="ttl_decrement",
        routing_key=settings.ttl_job.queue_name,
        expiration=1 * 60_000,
    )

    # api_test_msg: RmqClientsAction = RmqClientsAction(
    #     action="get_online_status",
    #     clients=[
    #         "a1b0004617c24558d080925",
    #         "a3b0000000c10221d290825",
    #     ],
    # )
    api_test2_msg: RmqClientsAction = RmqClientsAction(
        action="update_online_status", clients=[]
    )
    await job_publisher.publish(
        routing_key=settings.rmq.api_clients_queue,
        message=api_test2_msg,
        expiration=1 * 60_000,
    )
