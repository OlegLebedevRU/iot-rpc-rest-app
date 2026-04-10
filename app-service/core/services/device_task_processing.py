import logging
from typing import Any
from uuid import UUID

from core.config import RoutingKey, settings
from core.logging_config import setup_module_logger, log_rpc_debug
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

EVA_EXPIRATION_MS = 180_000  # 180 seconds


async def send_eva(
    sn: str,
    event_type_code: int,
    dev_event_id: int,
    corr_id: UUID | str | None,
    status: str,
):
    """
    Publish EVA (Event Acknowledgment) to srv.<SN>.eva.
    Replicates correlation, event_type_code, dev_event_id from the original EVT.
    """
    routing_key: str = str(
        RoutingKey(prefix=topology.prefix_srv, sn=sn, suffix=topology.suffix_event_ack)
    )
    payload = {"status": status}
    headers = {
        "event_type_code": str(event_type_code),
        "dev_event_id": str(dev_event_id),
    }
    if corr_id is not None:
        headers["correlationData"] = str(corr_id)

    log_rpc_debug(
        sn,
        "rpc.eva.publish",
        corr_id=corr_id,
        routing_key=routing_key,
        event_type_code=event_type_code,
        dev_event_id=dev_event_id,
        status=status,
    )
    await topic_publisher.publish(
        routing_key=routing_key,
        message=payload,
        correlation_id=corr_id,
        expiration=EVA_EXPIRATION_MS,
        headers=headers,
    )


async def send_tsk(sn: str, task: TaskCreate, stask: TaskResponse):

    task_device_topic = str(
        RoutingKey(settings.rmq.prefix_srv, sn, settings.rmq.suffix_task)
    )
    notify: TaskNotify = TaskNotify(
        id=stask.id, created_at=stask.created_at, header=task
    )
    log_rpc_debug(
        sn,
        "rpc.tsk.publish",
        corr_id=stask.id,
        routing_key=task_device_topic,
        method_code=notify.header.method_code,
        expiration=task.ttl * 60_000,
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
    sn: str,
    t_resp: dict[str, Any],
    correlation_id: UUID | str,
    expiration: int,
    method_code: str,
):
    routing_key: str = str(
        RoutingKey(prefix=topology.prefix_srv, sn=sn, suffix=topology.suffix_response)
    )
    log_rpc_debug(
        sn,
        "rpc.rsp.publish",
        corr_id=correlation_id,
        routing_key=routing_key,
        method_code=method_code,
        expiration=expiration,
        payload=t_resp,
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
    cmt_payload: dict[str, Any],
    webhook_msg: str,
    corr_id: UUID | str,
    dev_id: int,
    result_id: int,
    ext_id: int,
    status_code: int,
):

    routing_key: str = str(
        RoutingKey(prefix=topology.prefix_srv, sn=sn, suffix=topology.suffix_commited)
    )
    log_rpc_debug(
        sn,
        "rpc.cmt.publish",
        corr_id=corr_id,
        routing_key=routing_key,
        ext_id=ext_id,
        result_id=result_id,
        status_code=status_code,
        payload=cmt_payload,
    )
    await topic_publisher.publish(
        routing_key=routing_key,
        message=cmt_payload,
        correlation_id=corr_id,
        content_type="application/json",
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
        message=webhook_msg,
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
    log_rpc_debug(
        sn,
        "rpc.webhook.publish",
        corr_id=corr_id,
        routing_key=settings.webhook.webhooks_queue,
        dev_id=dev_id,
        ext_id=ext_id,
        result_id=result_id,
        status_code=status_code,
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
