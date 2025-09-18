# MQTT topic rules

### Topic name template

Example topic name:
Mqtt received topic= <dev/a3b0000000c10221d290825/req>
_to RabbitMQ routing-key translate = "dev.a3b0000000c10221d290825.req"_

````mermaid
---
title: "Topic name template"
---
packet
+3: "Direction prefix"
+1: "/"
+23: "Device Serial number"
+1: "/"
+3: "Action type suffix"


````
`Direction prefix = ["srv", "dev"]`
* srv - from SERVER to DEVICE
* dev - from DEVICE to SERVER

`Action suffix_1 = ["evt", "ack", "req", "res"]`

* evt - EVENT message from Device (not in RPC workflow)
* ack - acknowledge message for task init message
* req - from device request for get queued task
* res - send result after task complete

`Action suffix_2 = ["tsk", "rsp", "eva"]`
* tsk - immediate notify (without payload) message to device after task created
* rsp - from server response with task parameters (payload)
* eva - optional acknowledge to device after EVENT message received on server