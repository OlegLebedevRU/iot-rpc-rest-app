# Iot Async-RPC Core

[**Swarm of devices**] <--> [**Core**] <--> [**Control center**]

### Concepts:

- Iot is lifetime 'Loose Coupling' in Event-Driven Systems
- Thousands (swarms) of IOT devices should be represented by a simple and reliable end-to-end addressing system based on x509
- Remote calls are usually orders of magnitude slower and less reliable
- The App call is a simple request to REST-API, with async queued paradigm
- A combination of request/response and polling methods on remote machines
- Lightweight "The last mile protocol" MQTT 5.0
- TTL and priority for queued tasks

### The architectural stack:

- PostgreSQL
- RabbitMQ + MQTT Plugin (native) with permission definitions
- nginx + jwt (RSA) module
- CA (openssl, pyca/cryptography)
- optional mDNS like avahi (for local deployment case)
- app-services
- Swagger Api docs

## App stack [here](./docs/app_stack.md)


## Diagrams

- Task states [here](./docs/task_states.md)
- Workflow sequence [here](./docs/sequence.md)

## Device code examples, simulators
_Only two-way SSL authentication_
### MQTTX nocode (low code) scenarios with secure remote control:
_Windows/Linux PC as a device_
* Sending any file from a remote PC to Telegram on request via a web API.
* Remote start recording the screen (ffmpeg) and send the file.
* Remote launch any *.exe, *.cmd, *.sh, ...

### Python automation scenarios with secure remote control:

* Remotely launch the fullscreen alert form (tkinter) with the transmitted custom message.
* Remotely execute any python code.
* Raspberry PI. Remote start Camera-streaming custom session to WebRTC. 

### FreeRtos devices with secure remote control:

* ESP32, ESP-IDF. Remote PWM control LED.
* ESP32, ESP-IDF. Remote send/receive to RS-485 bus.
* ESP32, ESP-ADF. Remote invoke SIP-Call.
* ESP32, ESP-IDF. Remote control locker machine (open cell, set access code, etc).

* STM32. Remote starting measurements with custom parameters, sending an array of data. 