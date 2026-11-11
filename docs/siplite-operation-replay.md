# Siplite bounded replay for operation admission

Existing methods19 (ESP32 OTA),48 (RAW UDP),411 (STM32 flash),512 (STM32 image download) keep their existing method codes and payloads. No new event, I2C register or STM32 sequencing is introduced.

These operations need execution fencing independently of MQTT PUBACK/CMT. Before invoking a worker, siplite commits a private bounded receipt with task UUID, integral created_at and SHA256(method + compact parsed dt). Delivery bookkeeping is excluded. A retained UUID with changed intent returns409 before execution. Key order is retained conservatively. Durable-storage failure refuses execution.

The existing RES describes admission, not physical completion. A successful async launch returns200 with status accepted and method_code (512 may retain its existing download-task-started body). OTA and STM32 completion events retain their existing contracts. UDP success only describes queue admission, never receipt by the peer. Partial UDP admission is an explicit error with admitted/rejected counts; retry must not resend accepted datagrams.

The exact RES body/status/result_uid is committed before publication. The result UID is the canonical task UUID and is unchanged on retries. A duplicate returns the saved result without restarting an operation. An interrupted STARTED receipt becomes500 outcome_unknown, without re-executing effects. The operator reconciles through existing local operation status/firmware version/source hash/readback and submits a fresh UUID only when appropriate. A persisted accepted result is not proof of completion after power loss.

Eight shared slots retain unacknowledged results. A valid matching CMT may release a slot. Reuse advances a persisted created_at watermark: unknown older identities are rejected, never silently executed. Queue loss, disconnected broker and lost CMT only cause paced result retries; no repeated flash writes or reboot merely because MQTT is absent. The existing parser owns journal updates and retry, without another task.

Terminal event durability/reconciliation remains a separate implementation obligation; this admission fence does not claim exactly-once physical effects or reliable terminal-event delivery. Local HTTP operations without the task envelope remain outside this MQTT receipt journal.
