# Device emulator (mock RPC method 51 + healthcheck/test events)

A small standalone subproject that emulates an IoT device for the
MQTT v5 RPC protocol used by this repository
(see [`docs/mqtt-rpc-protocol.md`](../docs/mqtt-rpc-protocol.md)
and [`docs/event-protocol-mqtt.md`](../docs/event-protocol-mqtt.md)).

## What it does

* Connects to the configured MQTT broker over TLS using a client certificate.
* Subscribes to `srv/<SN>/tsk`, `srv/<SN>/rsp`, `srv/<SN>/cmt`, `srv/<SN>/eva`
  where `<SN>` is the `CN` field of the supplied client certificate.
* Implements a **mock handler for `method_code = 51` (open cell)** that
  emulates the real **3-phase physical flow** described in
  [`docs/ai-agent-integration-guide.md`](../docs/ai-agent-integration-guide.md):
  * On `tsk` for the device — sends an `ack` and a `req` with the same
    `correlationData`.
  * On `rsp` with `method_code=51` and payload like `{"dt":[{"cl": 5}]}`:
    1. **Immediately** publishes a `res` to `dev/<SN>/res` with
       `status_code=200`. This only confirms that the command was received
       by the device — **not** that the cell has been opened physically.
    2. After `CELL_OPEN_DELAY` seconds (default 1 s) publishes
       `event_type_code=13` (`CellOpenEvent`) carrying the cell number in
       tag `304` — this is the physical "cell opened" confirmation.
    3. `CELL_CLOSE_DELAY` seconds after event 13 (default 30 s), publishes
       `event_type_code=14` with the same format and the same cell number
       in tag `304` — emulating the physical closing of the cell.
* Once per minute publishes a **healthcheck event** (`event_type_code=44`).
* Once per minute publishes a **test event** (`event_type_code=90`).

No infrastructure is started apart from the Python container itself.

## Files

* `device_emulator.py` — the emulator implementation.
* `requirements.txt` — Python dependencies (`paho-mqtt`, `pyOpenSSL`).
* `Dockerfile` — `python:3.12-slim` image.
* `compose.yaml` — single-service Docker Compose definition.

## Certificates

Certificates are **never baked into the image**.  They live on the host and
are bind-mounted into the container at runtime.  The host directory is
supplied via environment variables passed on the
`docker compose` command line.

The directory may not yet contain the files when the container starts —
the emulator polls the configured paths every `CERT_WAIT_INTERVAL` seconds
(default 5) until the CA, client certificate and private key are all
present and parse as valid PEM.  Set `CERT_WAIT_TIMEOUT` to a positive
number of seconds to give up after a deadline (default `0` = wait forever).

## Configuration (environment variables)

| Variable | Default | Description |
|----------|---------|-------------|
| `MQTT_HOST` | `dev.leo4.ru` | MQTT broker hostname |
| `MQTT_PORT` | `8883` | MQTT broker TLS port |
| `CERTS_DIR` | *(required)* | Host directory bind-mounted to `/certs` |
| `CA_FILE_NAME` | `ca.crt` | CA certificate file name inside `CERTS_DIR` |
| `CERT_FILE_NAME` | `cert.pem` | Client certificate file name inside `CERTS_DIR` |
| `KEY_FILE_NAME` | `key.pem` | Client private key file name inside `CERTS_DIR` |
| `CERT_WAIT_INTERVAL` | `5` | Seconds between certificate readiness checks |
| `CERT_WAIT_TIMEOUT` | `0` | Seconds to wait for certificates (0 = forever) |
| `HEALTHCHECK_INTERVAL` | `60` | Seconds between healthcheck (`code=44`) events |
| `TEST_EVENT_INTERVAL` | `60` | Seconds between test (`code=90`) events |
| `CELL_OPEN_DELAY` | `1.0` | Seconds to wait after `res` before publishing `CellOpenEvent` (event 13) |
| `CELL_CLOSE_DELAY` | `30.0` | Seconds to wait after event 13 before publishing the cell-close event (event 14) |
| `LOG_LEVEL` | `INFO` | Python `logging` level |

## Running

From this directory:

```bash
CERTS_DIR=/host/path/to/certs \
CA_FILE_NAME=iot_leo4_ca.crt \
CERT_FILE_NAME=cert_0000000.pem \
KEY_FILE_NAME=key_0000000.pem \
MQTT_HOST=dev.leo4.ru \
MQTT_PORT=8883 \
docker compose up --build
```

The container will start and log lines such as:

```
Waiting for certificate files: CA=/certs/iot_leo4_ca.crt cert=... key=...
```

Once the files are placed in `CERTS_DIR` on the host, the emulator
proceeds to connect to the broker and starts producing events / handling
method 51 requests.

To stop:

```bash
docker compose down
```
