
````yaml
Enum
  READY = 0
  PENDING = 1
  LOCK = 2
  DONE = 3
  EXPIRED = 4
  DELETED = 5
  FAILED = 6
  UNDEFINED = 7
````

````mermaid
stateDiagram-v2
    state Main {
    [*] --> READY: Touch_task
    READY --> DONE: Result status_code = 200 from Device
    READY --> PENDING: ACK from Device
    READY --> LOCK: REQ from Device
    EXPIRED --> [*]
    
    LOCK --> FAILED: Error
    LOCK --> DONE: Result status_code = 200 from Device   
    PENDING --> DONE: Result status_code = 200 from Device
    PENDING --> LOCK: REQ from Device
    READY --> DELETED
    LOCK --> DELETED
    PENDING --> DELETED   
    DONE --> [*]
    FAILED --> [*]
    }
    
    state Delete {
        [*] --> DELETED
        DELETED --> [*]
    }
    READY --> EXPIRED: TTL=0   
    PENDING--> EXPIRED: TTL=0   
    LOCK --> EXPIRED: TTL=0
   
````