from __future__ import annotations

from core.config import settings
from core.topologys.declare import (
    BINDINGS,
    q_ctl,
    topic_exchange,
)


def test_remote_input_topology_declaration():
    # 1. Check q_ctl properties
    assert q_ctl.name == settings.rmq.ctl_queue_name
    assert q_ctl.name == "ctl"
    assert q_ctl.durable is False
    assert q_ctl.arguments.get("x-message-ttl") == 15000

    # 2. Check q_ctl in BINDINGS
    ctl_bindings = [
        (queue, rk, ex) for queue, rk, ex in BINDINGS if queue.name == "ctl"
    ]
    assert len(ctl_bindings) == 1
    queue, rk, ex = ctl_bindings[0]
    assert rk == "dev.*.ctl"
    assert ex.name == topic_exchange.name


def test_evt_binding_isolation_from_ctl():
    # Ensure q_evt binding is strictly dev.*.evt
    evt_bindings = [
        (queue, rk, ex) for queue, rk, ex in BINDINGS if queue.name == "evt"
    ]
    assert len(evt_bindings) == 1
    _, rk, ex = evt_bindings[0]
    assert rk == "dev.*.evt"
    assert rk != "dev.*.ctl"
    assert ex.name == topic_exchange.name


def test_existing_bindings_intact():
    expected_queues = {
        "req",
        "ack",
        "evt",
        "res",
        "out",
        "ctl",
        "app",
        "svc",
        "iot.device.connection.events",
        settings.ttl_job.queue_name,
        settings.rmq.api_clients_queue,
        settings.webhook.webhooks_queue,
        settings.billing.billing_queue,
    }
    bound_queues = {q.name for q, _, _ in BINDINGS}
    assert expected_queues.issubset(bound_queues)
