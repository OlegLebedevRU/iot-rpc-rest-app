# Strict camera MQTT5 transport metadata

Camera CTLv1 enrollment/readiness/admission accepts QoS1, retain=false and exact
36-byte UUID correlation data. A QoS1 subscription does not upgrade a QoS0
publication. RabbitMQ's AMQP0.9.1→MQTT5 conversion maps delivery_mode2 to QoS1,
delivery_mode1 to QoS0 and correlation_id shortstr to binary Correlation Data.
Reference: https://www.rabbitmq.com/docs/4.1/conversions

The live enrollment diagnosis found HELLO accepted and OFFER emitted, but no
PROOF. The exact1548-byte OFFER was accepted by the production C core offline.
The installed shared FastStream publisher default persist=false produced AMQP
delivery_mode1, so the strict camera envelope correctly rejected its MQTT QoS0.
Correlation already encoded as a36-byte UTF-8 UUID; do not weaken firmware checks.

CameraRuntime.publish now overrides persist=true per call, leaving the shared
publisher defaults and noncamera behavior unchanged. aio-pika numeric expiration
is seconds, so passing a remaining5000ms integer previously encoded5000000ms.
The camera method now passes timedelta(milliseconds=remaining) instead. Zero,
negative, noninteger and above60000ms budgets are rejected before publication.
Existing pump/authority checks still supply the original remaining deadline;
payload issued/expires, binding, counters and readiness are not rewritten.

Actual AioPikaParser serialization regression tests cover OFFER/COMMIT/readiness/
START/RENEW/STOP with shrinking1ms/1234ms residual budgets: delivery_mode2,
correlation bytes36, unchanged header types and exact transport expiration. Shared
noncamera defaults remain persist=false. No broker/global configuration, schema,
gate, database migration, firmware envelope or camera pipeline change is needed.
