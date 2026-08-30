import asyncio
import importlib
import logging
import random
from contextlib import suppress
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI
from fastapi.openapi.docs import (
    get_redoc_html,
    get_swagger_ui_html,
    get_swagger_ui_oauth2_redirect_html,
)
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi_pagination import add_pagination
from sqlalchemy import text

# Импортируем маршруты и конфигурацию
from api import router as api_router
from core import settings
from core.config import mask_amqp_url
from core.fs_broker import fs_router
from core.logging_config import setup_module_logger
from core.models import db_helper
from core.services.device_task_processing import act_ttl
from core.services.devices import DeviceService
from core.services.billing import BillingService
from core.topologys.declare import declare_x_q

# Импортируем теги и константы из нового файла
from config.tags import TAGS_METADATA

log = setup_module_logger(__name__, "app_create_app.log")
logging.getLogger("logger_proxy").disabled = True

_RMQ_DEFINITIONS_SYNC_LOCK_KEY = 2026080501
_RMQ_DEFINITIONS_SYNC_ATTEMPTS = 5
_SUBSCRIBER_MODULES = (
    "core.topologys.fs_queues",
    "core.topologys.internal_bus",
)

SUMMARY = """
## 📚 Основные элементы АПИ

### 🧩 Поддерживаемые разделы
| Тег | Краткое описание |
|-----|------------------|
| **Device tasks** | Команды устройствам (создание и отслеживание задач) |
| **Device events** | Получение и фильтрация событий с пагинацией и инкрементальной выборкой |
| **Devices** | Реестр устройств организации и управление тегами |
| **Gauges** | Показания датчиков и метрик оборудования |
| **Webhooks** | Настройка вебхуков для получения событий |

### 🔐 Безопасность
- Все эндпоинты требуют заголовок `x-api-key`
- Принадлежность ресурсов к организации проверяется автоматически

"""


# Connection exceptions that are worth retrying (network / broker not ready).
# We try to import aio_pika-specific errors; fall back gracefully if absent.
_RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    TimeoutError,
    asyncio.TimeoutError,
    OSError,
    ConnectionError,
    Exception,
)
try:
    import aio_pika.exceptions  # type: ignore[import]

    _RETRYABLE_EXCEPTIONS = _RETRYABLE_EXCEPTIONS + (
        aio_pika.exceptions.AMQPConnectionError,
    )
except ImportError, AttributeError:
    pass
try:
    import aiormq.exceptions  # type: ignore[import]

    _RETRYABLE_EXCEPTIONS = _RETRYABLE_EXCEPTIONS + (
        aiormq.exceptions.AMQPConnectionError,
    )
except ImportError, AttributeError:
    pass


def _registered_subscriber_count() -> int:
    return len(getattr(fs_router.broker, "_subscribers", []))


def _ensure_rabbit_subscribers_registered() -> None:
    """Import all modules that register FastStream subscribers.

    FastStream decorators run at import time.  Keeping these imports explicit in
    the application factory prevents a startup with declared queues but no
    consumers after refactors or broker restarts.
    """
    before = _registered_subscriber_count()
    for module_name in _SUBSCRIBER_MODULES:
        importlib.import_module(module_name)
    after = _registered_subscriber_count()
    log.info("RabbitMQ subscribers registered: %d (before=%d)", after, before)


async def _start_broker_with_retry() -> None:
    """Start the FastStream broker with exponential backoff + jitter.

    Retry policy is read from ``settings.faststream``.  Each attempt is wrapped
    in ``asyncio.wait_for`` so a single hung TCP connect does not block forever.

    aio-pika's robust connection (used internally by FastStream) will handle
    *runtime* reconnects after a successful startup.  This function only covers
    the "broker not yet reachable at boot" scenario.
    """
    cfg = settings.faststream
    masked_url = mask_amqp_url(str(cfg.url))
    max_retries = cfg.connect_max_retries  # -1 → infinite
    attempt = 0
    delay = cfg.connect_initial_delay

    while True:
        try:
            if cfg.connect_timeout > 0:
                await asyncio.wait_for(
                    fs_router.broker.start(), timeout=cfg.connect_timeout
                )
            else:
                await fs_router.broker.start()
            log.info(
                "Broker connected successfully on attempt %d: %s",
                attempt + 1,
                masked_url,
            )
            return
        except _RETRYABLE_EXCEPTIONS as exc:
            attempt += 1
            exhausted = (max_retries >= 0) and (attempt >= max_retries)
            if exhausted:
                log.error(
                    "Broker connection failed after %d attempt(s): %s — giving up. URL: %s",
                    attempt,
                    exc,
                    masked_url,
                )
                raise
            # Add jitter to avoid thundering-herd on mass restarts.
            jitter = random.uniform(0, cfg.connect_jitter * delay)
            actual_delay = delay + jitter
            log.warning(
                "Broker connection attempt %d failed (%s). Retrying in %.1fs… URL: %s",
                attempt,
                exc,
                actual_delay,
                masked_url,
            )
            await asyncio.sleep(actual_delay)
            delay = min(delay * cfg.connect_backoff_factor, cfg.connect_max_delay)


async def _rmq_topology_watchdog() -> None:
    """Periodically re-declare RabbitMQ topology after runtime broker restarts.

    aio-pika robust connections restore consumers after reconnect, but non-durable
    queues/bindings can be lost when the broker is restarted from a clean or
    partially restored state.  Re-declaration is idempotent and keeps consumers'
    queues available without requiring an app restart.
    """
    interval = settings.faststream.topology_watchdog_interval
    while True:
        await asyncio.sleep(interval)
        try:
            await declare_x_q()
            log.info(
                "RabbitMQ topology watchdog completed; registered_subscribers=%d",
                _registered_subscriber_count(),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("RabbitMQ topology watchdog failed; will retry: %s", exc)


async def _sync_rmq_device_definitions_on_startup() -> None:
    """Reconcile RabbitMQ MQTT users and ACL from the devices stored in DB.

    RabbitMQ definitions are persisted in `/var/lib/rabbitmq`, but they can be lost
    after accidental volume removal or startup from a clean broker.  The DB remains
    the source of truth for registered devices, so app startup re-applies users,
    permissions and topic-permissions idempotently.  A PostgreSQL advisory lock
    prevents a thundering herd when gunicorn starts multiple workers.
    """
    from core.services.rmq_admin import RmqAdmin

    for attempt in range(1, _RMQ_DEFINITIONS_SYNC_ATTEMPTS + 1):
        try:
            async with db_helper.session_factory() as session:
                async with session.begin():
                    lock_acquired = await session.scalar(
                        text("SELECT pg_try_advisory_xact_lock(:lock_key)"),
                        {"lock_key": _RMQ_DEFINITIONS_SYNC_LOCK_KEY},
                    )
                    if not lock_acquired:
                        log.info(
                            "RabbitMQ device ACL sync skipped: another worker holds the lock"
                        )
                        return

                    result = await RmqAdmin.set_device_definitions(session)

            log.info("RabbitMQ device ACL sync completed: %s", result)
            return
        except Exception as exc:
            if attempt >= _RMQ_DEFINITIONS_SYNC_ATTEMPTS:
                log.error(
                    "RabbitMQ device ACL sync failed after %d attempts; startup continues: %s",
                    attempt,
                    exc,
                )
                return

            delay = min(2**attempt, 10)
            log.warning(
                "RabbitMQ device ACL sync attempt %d/%d failed (%s). Retrying in %ds…",
                attempt,
                _RMQ_DEFINITIONS_SYNC_ATTEMPTS,
                exc,
                delay,
            )
            await asyncio.sleep(delay)


async def _initial_device_connections_sync_cold_boot() -> None:
    """Non-blocking background initial sync for device connections at startup."""
    log.info(
        "Starting background initial device connections reconciliation (cold boot)..."
    )
    try:
        await asyncio.sleep(1.0)
        async for session in db_helper.session_getter():
            await DeviceService.reconcile_device_connections(
                session,
                time_budget=settings.rmq.device_sync_time_budget_sec,
                chunk_size=settings.rmq.device_sync_chunk_size,
            )
            break
        log.info(
            "Background initial device connections reconciliation completed."
        )
    except Exception as exc:
        log.warning(
            "Initial device connections reconciliation encountered an error: %s",
            exc,
        )


async def _periodic_device_reconciliation_job() -> None:
    """Periodic background reconciliation of device connections."""
    async for session in db_helper.session_getter():
        try:
            await DeviceService.reconcile_device_connections(
                session,
                time_budget=settings.rmq.device_sync_time_budget_sec,
                chunk_size=settings.rmq.device_sync_chunk_size,
            )
        except Exception as e:
            log.error("Periodic device reconciliation job failed: %s", e)
        break


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    await _start_broker_with_retry()
    await declare_x_q()
    await _sync_rmq_device_definitions_on_startup()
    topology_watchdog_task: asyncio.Task | None = None
    if settings.faststream.topology_watchdog_enabled:
        topology_watchdog_task = asyncio.create_task(_rmq_topology_watchdog())
        log.info(
            "RabbitMQ topology watchdog started: interval=%.1fs",
            settings.faststream.topology_watchdog_interval,
        )
    cold_boot_task = asyncio.create_task(_initial_device_connections_sync_cold_boot())
    scheduler = AsyncIOScheduler()
    scheduler.configure(jobstores={"default": MemoryJobStore()})
    try:
        scheduler.add_job(
            act_ttl,
            args=[settings.ttl_job.tick_interval],
            coalesce=True,
            trigger=IntervalTrigger(minutes=settings.ttl_job.tick_interval),
            id=settings.ttl_job.id_name,
            replace_existing=True,
        )
        scheduler.add_job(
            _periodic_device_reconciliation_job,
            coalesce=True,
            trigger=IntervalTrigger(seconds=settings.rmq.device_poll_interval_sec),
            id="device_reconciliation_job",
            replace_existing=True,
        )
        # Billing: monthly calculation job — runs daily at 00:15,
        # but only performs calculation on the 1st of each month.
        from apscheduler.triggers.cron import CronTrigger

        scheduler.add_job(
            _billing_monthly_job,
            coalesce=True,
            trigger=CronTrigger(day=1, hour=0, minute=15),
            id="billing_monthly_calc",
            replace_existing=True,
        )
        scheduler.start()
    except Exception as e:
        log.info(f"Исключение scheduler: {str(e)}")

    yield

    if not cold_boot_task.done():
        cold_boot_task.cancel()
        with suppress(asyncio.CancelledError):
            await cold_boot_task
    if topology_watchdog_task is not None:
        topology_watchdog_task.cancel()
        with suppress(asyncio.CancelledError):
            await topology_watchdog_task
    await db_helper.dispose()
    scheduler.shutdown()
    # Wrap close() so a broker that is already gone doesn't raise on shutdown.
    try:
        await fs_router.broker.close()
    except (OSError, ConnectionError, RuntimeError) as exc:
        log.warning("Ignoring error while closing broker: %s", exc)


async def _billing_monthly_job() -> None:
    """APScheduler job: calculate billing for the previous month on the 1st."""
    async for session in db_helper.session_getter():
        try:
            count = await BillingService.calculate_previous_month(session)
            log.info("Billing monthly job completed: %d orgs processed", count)
        except Exception as e:
            log.error("Billing monthly job failed: %s", e)
        break


def get_scalar_api_reference_html(
    openapi_url: str,
    title: str = "Leo4 IoT Platform - API Reference",
) -> str:
    return f"""<!doctype html>
<html>
  <head>
    <title>{title}</title>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <link rel="icon" type="image/x-icon" href="/favicon.ico">
    <style>
      body {{
        margin: 0;
        padding: 0;
      }}
    </style>
  </head>
  <body>
    <script
      id="api-reference"
      data-url="{openapi_url}"
      src="https://cdn.jsdelivr.net/npm/@scalar/api-reference"
    ></script>
  </body>
</html>"""


def register_static_docs_routes(app: FastAPI) -> None:
    @app.get("/docs", include_in_schema=False)
    async def scalar_docs_html() -> HTMLResponse:
        openapi_url = str(app.openapi_url or "/openapi.json")
        return HTMLResponse(
            get_scalar_api_reference_html(
                openapi_url=openapi_url,
                title=f"{app.title} - API Reference",
            )
        )

    @app.get("/swagger", include_in_schema=False)
    @app.get("/legacy-docs", include_in_schema=False)
    async def custom_swagger_ui_html() -> HTMLResponse:
        return get_swagger_ui_html(
            openapi_url=str(app.openapi_url),
            title=app.title + " - Swagger UI",
            oauth2_redirect_url=app.swagger_ui_oauth2_redirect_url,
            swagger_js_url="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js",
            swagger_css_url="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css",
            swagger_favicon_url="/favicon.ico",
        )

    @app.get(str(app.swagger_ui_oauth2_redirect_url), include_in_schema=False)
    async def swagger_ui_redirect() -> HTMLResponse:
        return get_swagger_ui_oauth2_redirect_html()

    @app.get("/redoc", include_in_schema=False)
    async def redoc_html() -> HTMLResponse:
        return get_redoc_html(
            openapi_url=str(app.openapi_url),
            title=app.title + " - ReDoc",
            redoc_js_url="https://unpkg.com/redoc@next/bundles/redoc.standalone.js",
        )


def create_app(create_custom_static_urls: bool = True) -> FastAPI:
    _ensure_rabbit_subscribers_registered()
    app = FastAPI(
        title="Leo4",
        version="0.2.1",
        description=f"{SUMMARY}",
        default_response_class=JSONResponse,
        lifespan=lifespan,
        openapi_tags=TAGS_METADATA,
        docs_url=None,
        redoc_url=None,
    )
    add_pagination(app)
    app.include_router(api_router)
    app.include_router(fs_router, include_in_schema=False)

    # Billing API request counter middleware
    from core.middleware.billing_counter import BillingApiCounterMiddleware

    app.add_middleware(BillingApiCounterMiddleware)

    register_static_docs_routes(app)

    return app
