# Iot Async-RPC Core

[**Swarm of devices**] <--> [**Core**] <--> [**Control center**]

### Concepts:

- Iot is lifetime 'Loose Coupling' in Event-Driven Systems
- Thousands (swarms) of IOT devices should be represented by a simple and reliable end-to-end addressing system based on x509
- Remote calls are usually orders of magnitude slower and less reliable
- The App call is a simple request to REST-API, with async queued paradigm
- A combination of request/response and polling methods on remote machines
- Lightweight "The last mile protocol" MQTT 5.0

### The architectural stack:

- PostgreSQL
- RabbitMQ + MQTT Plugin (native) with permission definitions
- nginx + jwt (RSA) module
- CA (openssl, pyca/cryptography)
- optional mDNS like avahi (for local deployment case)
- app-services
- Swagger Api docs

### App:

- Python3
- FastAPI
- FastStream
- Pydantic
- SQLAlchemy
- Alembic

### Infra:

- Docker Compose
- PKI (X.509)

### Examples

#### Windows, Linux
Python agent

#### FreeRtos
c
ESP-IDF

```mermaid
sequenceDiagram
    box  rgb(55, 51, 25)
    actor ClientApp
    end
    participant API  
    participant Core


    rect rgb(0, 102, 204)
    ClientApp->>+API: Touch new task ( device, priority, ttl )
    Note left of API: Validate request headers
    
    alt Valid request
        
        API->>+Core: Init new task
        activate Core
        API->>ClientApp: Response OK (task_id: uuid4)
       
    else Invalid request
        rect rgb(153, 0, 0)
        API->>ClientApp: Response Error code
        end

    end
    end 

    deactivate API
    
    par Core to Queue       
        rect rgb(0, 102, 204)
        
        create participant Queue
        
        Core->>-Queue:Push task to queue
        end
    and Core to Device
        rect rgb(0, 102, 204)
        alt Device is online
            Core->>+Device:Immediate notification of a new task
            activate Device
            deactivate Core
       
            Note right of Device: Start Job
            Device->>+Core:Ack ( Optional )
            Core->>-Core: Set Pending Status
        
        else Device is offline
            rect rgb(153, 0, 0)
            Core--xDevice:Mqtt pub error
            end
        end
        end        
    end
    rect rgb(0, 102, 204)
    Device->>+Core: Request current task
    deactivate Device
    rect rgb(0, 0, 204)
    Queue<<->>Core: Get task from queue
    end
    Core->>Core: Locked Status
    Core->>-Device: Response current task with payload
    activate Device
    Note right of Device: Worker
    Device->>-Core: Pub Result to 
    activate Core
    Core->>Core: Save Result, Done task    
    deactivate Device
    deactivate Core
    Note right of Device: End Job
    end
    rect rgb(0, 102, 204)
    Loop loop Request task status
   
    ClientApp->>API: Request task status
    Note left of API: Validate request headers
    API<<->>Core: Get task data
    API->>ClientApp: Response task data (Status)
    end
    end
    rect rgb(0, 102, 204)
    Loop loop Periodic request to Task queue
    rect rgb(100, 102, 204)
    Core->Device:Device started at any time
    end
    
    
    Device->>+Device: Periodic timer
    Note right of Device: Start job
    Device->>+Core: Request task from FIFO
    rect rgb(0, 0, 204)
    Queue<<->>Core: Get task from queue
    end
    Core->>Core: Locked Status
    Core->>-Device: Response selected task with payload OR zero-task if None
    activate Device
    Note right of Device: Worker
    Device->>-Core: Pub Result to 
    activate Core
    Core->>Core: Save Result, Done task    
    deactivate Device
    deactivate Core
    Note right of Device: End Job
    end
    end
    rect rgb(0, 102, 204)
    Loop loop Request task status
   
    ClientApp->>API: Request task status
    Note left of API: Validate request headers
    API<<->>Core: Get task data
    API->>ClientApp: Response task data (Status)
    end
    end
    
```
