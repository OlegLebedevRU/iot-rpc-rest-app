

### TTL

- TTL is measured in minutes.
- The initial TTL value is set once in the "Touch task" API-request.
- Core updates the TTL (decreases the value by 1) every minute.
- The maximum TTL value in minutes = 44640 or approximately equal to 1 month.

#### Polling strategy and TTL

Tasks with `ttl = 0` are **excluded from the polling selection** (`req` with zero UUID).
The server selects the next task for the device according to this order:

1. Only tasks with `status < DONE` are eligible
2. Tasks with `ttl = 0` are excluded (`WHERE ttl > 0`)
3. Sorted by `priority DESC`, then `ttl ASC`, then `created_at ASC`
4. The first task in this order goes to `rsp`

This means that a task with a higher priority will always be selected first.
Among tasks with the same priority, the one closest to expiration (smallest positive TTL) takes precedence.
If both priority and TTL are equal, the oldest task (`created_at`) wins.

#### Case TTL=0: 

It can be used if a task delivery guarantee is not required and feedback from the device is not required. For example, for reverse polling without waiting for correlation of the result.

> ⚠️ This leads to a race risk when the kernel TTL job finds a zero TTL and puts the task in the `EXPIRED` state while the device simultaneously requests this task via trigger (non-zero correlation).

> **Note:** tasks with `ttl = 0` can still be delivered via **trigger** flow (`tsk` → `req` with specific correlation UUID), but they will **not** be selected during **polling** (`req` with zero UUID).

#### See also

- [`mqtt-rpc-protocol.md`](./mqtt-rpc-protocol.md) — Full RPC protocol specification with polling strategy
- [`1-task-workflow-doc.md`](./1-task-workflow-doc.md) — Task API workflow documentation
