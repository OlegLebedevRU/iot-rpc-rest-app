# Task TTL in MQTT RPC

`ttl` is measured in minutes and remains part of the REST and MQTT task header.
The server stores an internal `expires_at` deadline in PostgreSQL. A periodic job
marks overdue active tasks `EXPIRED`; repeated or delayed job runs do not change
the deadline. REQ checks the deadline itself, so an overdue task cannot be
dispatched while waiting for that job.

For `ttl > 0`, the deadline is task creation plus `ttl` minutes. REST GET and
LIST report the remaining minutes rounded up while the task is active. Polling uses
the following order: `priority DESC`, remaining minutes `ASC`, creation time
`ASC`. Polling excludes `ttl=0` tasks and expired deadlines.

`ttl=0` is a trigger-only, short-lived task. It can be requested by its task
UUID following `tsk` for at most one minute after creation. The external TTL
field stays `0`; the minute is an internal trigger window. Polling with the
zero UUID never selects it. A late REQ receives the normal no-task response.

An incoming RES is stored and acknowledged even if its task has become
`EXPIRED`; the status stays `EXPIRED`. A new result received no later than three
minutes after `expires_at` creates the normal `msg-task-result` webhook message.
A later result is stored and acknowledged without creating a webhook. Delivery
of a webhook already created follows the webhook subsystem's own rules. A
duplicate RES receives the original `result_id` in CMT and creates no new
result or webhook. After DELETE, RES is stored and acknowledged; status stays
`DELETED` and no webhook is created.

For tasks already `EXPIRED` before the deadline migration, the historical
expiration instant cannot be reconstructed from the old minute counter. Their
deadline is left unknown; late results on these records are still stored and
acknowledged, but do not create a new webhook.

RabbitMQ message expiration is separate from task TTL. The AMQP publisher API
takes seconds or `timedelta`; it must receive the remaining transport lifetime,
not a millisecond count passed as seconds.
