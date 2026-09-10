# Developer Guidelines & Architecture Reference — Leo4 IoT Platform

This guide contains project-specific architecture, configuration, testing, and development guidelines for advanced developers working on the Leo4 IoT Platform (`iot-rpc-rest-app`).

---

## 1. Build & Configuration Instructions

### Tech Stack Overview
- **Runtime & Language**: Python `>= 3.14` (`from __future__ import annotations`, strict type annotations).
- **Package & Dependency Manager**: `uv` (`uv.lock`). Do **not** use `pip` directly or edit `uv.lock` manually.
- **Core Frameworks**: FastAPI (REST & WebSockets) + FastStream (RabbitMQ / MQTT 5 broker integration).
- **Persistence & ORM**: PostgreSQL via SQLAlchemy 2.0 (asyncio + `asyncpg`), migrations managed by Alembic.
- **Message Broker & Transport**: RabbitMQ 4 (with `rabbitmq_mqtt` & `rabbitmq_management` plugins enabled), MQTT 5 transport with PKI / mTLS authentication.
- **Reverse Proxy & Security**: Nginx (external; containers and configs are not managed by this project, repo configs in `nginx/` and `nginx-configs/` are non-authoritative).
- **Containerization**: Docker Compose (`compose.yaml`).

### Environment & Dependency Setup
1. **Install dependencies**:
   ```bash
   uv sync
   ```
2. **Package management**:
   - Add new dependencies: `uv add <package-name>`
   - Update lockfile: `uv lock`
   - Keep packages updated to modern, compatible versions according to project policy.

### Configuration (`app-service/core/config.py`)
Configuration is managed via Pydantic `BaseSettings` (`pydantic-settings`).
- **Environment variables prefix**: `APP_CONFIG__` with double-underscore `__` nested delimiters.
- **Config sources**: `.env.template`, `app-service/.env` (and environment variables).

#### Key Environment Variables
| Variable | Description | Default / Example |
|---|---|---|
| `APP_CONFIG__DB__URL` | PostgreSQL async connection URL | `postgresql+asyncpg://user:pass@localhost:5432/postgres` |
| `APP_CONFIG__DB__POOL_SIZE` | SQLAlchemy connection pool size | `50` |
| `APP_CONFIG__DB__MAX_OVERFLOW` | Max pool overflow connections | `10` |
| `APP_CONFIG__FASTSTREAM__URL` | RabbitMQ AMQP connection URL | `amqp://user:pass@rabbitmq:5672//` |
| `APP_CONFIG__FASTSTREAM__REWRITE_EXTERNAL_HOST_TO_COMPOSE` | Auto-rewrite non-local broker hosts to Compose container host | `true` |
| `APP_CONFIG__FASTSTREAM__CONNECT_MAX_RETRIES` | Connection retry attempts on startup | `30` |
| `APP_CONFIG__FASTSTREAM__TOPOLOGY_WATCHDOG_ENABLED` | Re-declares broker topology if broker restarts | `true` |
| `APP_CONFIG__AUTH__API_KEYS` | Raw API keys map (`key:org_id,key2:org_id2`) | `testkey_0_a:0,testkey_1_b:1` |
| `APP_CONFIG__WEBHOOK__TIMEOUT` | HTTP webhook client timeout in seconds | `10.0` |
| `APP_CONFIG__WEBHOOK__MAX_RETRIES` | Webhook dispatch retry limit | `2` |

### Database Migrations (Alembic)
- Apply latest migrations:
  ```bash
  uv run alembic upgrade head
  ```
- Generate autodetected migration:
  ```bash
  uv run alembic revision --autogenerate -m "describe_migration"
  ```

### Running Infrastructure via Docker Compose
```bash
docker compose up -d --build app1
docker compose logs -f app1
```
- **Infrastructure Protection**: NEVER recreate `pg`, `rabbitmq`, `nginx`, `nginx-mutual`, `pgadmin`, or `certbot` containers without explicit instructions.
- **Nginx & Gateway Status**: Nginx containers and all nginx configurations are NOT managed by this project. Any nginx configs in `nginx/` or `nginx-configs/` must be treated as non-authoritative and are excluded from the compose infrastructure of this project. Direct editing of nginx configs on the server is strictly prohibited during debugging or troubleshooting; notify the owner and request manual instructions.
- **Certificates & mTLS**: Certificate files (`*.crt`, `*.pem`, `*.key`) are bind-mounted at runtime from `./crt/` and are never baked into container images.
- **Manual `app1` deployment**: When deploying only the application service, follow `docs/manual-app1-deploy-runbook.md`. Host build (`docker compose build app1 && docker compose up -d --no-deps app1`) is default; GHCR pull only on explicit request. Do not recreate database, broker, or proxy containers.

---

## 2. Testing Information

### Test Runner & Framework
- Test runner: `pytest` with `anyio` async backend plugin (`plugins = ["anyio"]`).
- Configuration: defined in `pyproject.toml` (`testpaths = ["app-service/tests"]`).
- Default exclusions: `norecursedirs` ignores `.git`, `.venv`, build artifacts, and subproject directories.

### Test Configuration (`app-service/tests/conftest.py`)
- Automatically inserts `app-service/` into `sys.path`.
- Sets default test environment variables (`APP_CONFIG__FASTSTREAM__URL`, `APP_CONFIG__DB__URL`, `APP_CONFIG__AUTH__API_KEYS="test:1"`).
- Replaces `logging.handlers.RotatingFileHandler` with `logging.NullHandler()` to prevent test file pollution.
- Monkeypatches `Path.mkdir` to safely bypass `/var/log/app` directory creation during local runs.
- Automatically marks tests tagged with `@pytest.mark.asyncio` as `pytest.mark.anyio`.
- Ignores stubs via `collect_ignore_glob = ["api/v1/test_postamat.py"]`.

### Running Tests
```bash
# Run all tests in the project
uv run pytest

# Run a specific test file
uv run pytest app-service/tests/core/services/test_rmq_admin.py

# Run with verbose output and specific keywords
uv run pytest -v -k "test_routing_key"
```

### Adding New Tests
When adding tests:
1. Place test files under `app-service/tests/` matching the code hierarchy (`api/v1/`, `core/diagnostics/`, `core/services/`, `core/schemas/`, `core/topologys/`).
2. Prefix test files with `test_` and test functions with `test_`.
3. For asynchronous functions, decorate test functions with `@pytest.mark.asyncio` or `@pytest.mark.anyio`.
4. Use `monkeypatch` or `unittest.mock.AsyncMock` to isolate database queries (`AsyncSession`) and external integrations (`RmqAdminApi`, FastStream broker, HTTP endpoints).

### Verified Test Demonstration Example
Below is a working example demonstrating unit tests, schema/config validation, and async testing in this repository:

```python
import pytest
from core.config import parse_api_keys, RoutingKey


def test_routing_key_formatting():
    """Verify that RoutingKey constructs dot-separated topic strings."""
    rk = RoutingKey(prefix="dev", sn="SN12345", suffix="evt")
    assert str(rk) == "dev.SN12345.evt"
    assert repr(rk) == "dev.SN12345.evt"


def test_parse_api_keys_valid():
    """Verify API key mapping parser handles valid and invalid entries."""
    raw_keys = "key1:100, key2:200, invalid_key"
    parsed = parse_api_keys(raw_keys)
    assert parsed == {"key1": 100, "key2": 200}


@pytest.mark.asyncio
async def test_async_sample_execution():
    """Verify async execution via pytest-anyio compatibility."""
    async def sample_coroutine():
        return 42

    result = await sample_coroutine()
    assert result == 42
```

---

## 3. Project Rules & Development Guidelines

### Repository Navigation & Scope Exclusion
- **Directory Exclusion Guardrail**: When reviewing, exploring, or analyzing repository code, **never** inspect `certbot`, `device-emulator`, `examples`, `mcp`, or `robotics` folders unless explicitly requested in the prompt. Focus strictly on `app-service`, `docs`, `docker-files`, `rmq`, and root configs.
- **Excluded Agent Context**: `device-emulator/`, `mcp/`, `examples/`, and `robotics/` are excluded from mandatory agent context.
- **Nginx Infrastructure Exclusion**: `nginx/` and `nginx-configs/` are non-authoritative and excluded from compose infrastructure.

### Code Hygiene & Bloat Prevention
- **Package Modernization**: Strive to keep dependencies updated to modern, secure, and maintained versions via `uv`.
- **Zero Artifact Policy**: Never leave garbage, temporary test files, local debug dumps, or untracked test scripts in the repository. Verify repository state before completing any task.
- **Code Pruning**: Always inspect modified files for obsolete code, deprecated logic, unreferenced imports, or overly bloated functions. Clean up dead code and avoid sprawling monolith functions.

### Concurrency & Blocking I/O Optimization (Critical)
- **Strictly Async-First**: The codebase runs on FastAPI and FastStream event loops. **Never** make blocking synchronous calls (e.g. `time.sleep`, synchronous database drivers, `requests`). Use `asyncio.sleep`, `httpx.AsyncClient`, `asyncpg`, and `aio-pika`.
- **Database Operations**:
  - Optimize inserts and updates (batching, bulk queries).
  - Use connection pooling parameters wisely (`pool_size`, `max_overflow`).
  - Always manage transactions explicitly using async context managers with `AsyncSession`.
- **RabbitMQ & AMQP Operations**:
  - Minimize unnecessary calls to RabbitMQ Admin API.
  - Skip reconciliation if no device entities have changed.
  - Rely on FastStream's pre-declared topologies and automatic watchdog for channel reconnection.

### High-Cost Resource Operations Guardrail
- **Chat Confirmation**: Always ask for confirmation in the chat before implementing features or running procedures that present a risk of high compute, memory, or disk consumption (e.g., intensive data migrations, heavy background reprocessing, large payload streaming, massive bulk operations).

### Domain Rules & Protocol Invariants
- **`status=3 (DONE)` Invariant**: A task status of `DONE` indicates that the command was successfully acknowledged / accepted by the device transport; it does **not** signify physical hardware execution. Physical completion is confirmed exclusively via device event reports (`event_type_code` 13/14, etc.).
- **TTL Semantics**: Task TTL decrements according to `docs/TTL.md`. When `TTL=0`, the task is marked `EXPIRED`, not `DONE`.
- **MQTT Topic Structure**: Follow `docs/mqtt_topic_rules.md` (topics are extended):
  - Broker/Server topics: `srv/<SN>/{tsk,rsp,cmt,eva,ctl}`
    - `tsk`: task trigger/announcement
    - `rsp`: task payload/parameters (RPC response)
    - `cmt`: server delivery commit
    - `eva`: event acknowledgement
    - `ctl`: remote input control plane commands (`l4desk`)
  - Device topics: `dev/<SN>/{req,ack,res,evt,out,ctl}` (plus reserved `app`, `svc` queues)
    - `req`: task request (RPC poll/trigger request)
    - `ack`: command acknowledgement
    - `res`: task execution result (RPC result)
    - `evt`: asynchronous device events
    - `out`: volatile streaming output (live logs, remote diagnostics stdout/stderr)
    - `ctl`: remote input presence and ACK/NACK (`l4desk`)
    (where `<SN>` is the client certificate Common Name).
- **Correlation Data**: Correlation data (`correlation_id`) is mandatory on all RPC requests and responses for message mapping.
- **Method Codes & Registry**: The registry in `docs/method-codes-reference.md` is incomplete in practice, dynamically expands, and may lag behind actual usage. This must NOT block agent work; however, if mutations (new or deprecated `method_code`s) are encountered, it is recommended to clarify them with the owner/user.
- **Error Codes**: Use standard error codes from `docs/method-codes-reference.md` (e.g., `65535` / `0xFFFF` for `CMD_INVALID_JSON`).
- **Container Protection Invariant**: Never recreate `pg`, `rabbitmq`, `nginx`, `nginx-mutual`, `pgadmin`, `certbot` containers without explicit instructions.
- **Server Nginx Invariant**: Direct modification of nginx configs on the server is strictly forbidden during debugging or troubleshooting; notify the owner and obtain manual instructions.
