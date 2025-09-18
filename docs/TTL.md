

### TTL

- TTL is measured in minutes.
- The initial TTL value is set once in the "Touch task" API-request.
- Core updates the TTL (decreases the value by 1) every minute.
- The maximum TTL value in minutes = 44640 or approximately equal to 1 month.

#### Case TTL=0: 

``
It can be used if a task delivery guarantee is not required and feedback from the device is not required. For example, for reverse polling without waiting for correlation of the result.
``

`   This leads to a race risk when the kernel task finds a zero ttl and puts the task in the expired state and the device simultaneously requests this task.
`