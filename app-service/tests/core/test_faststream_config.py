"""Tests for FastStreamConfig URL-rewrite helper and broker retry logic."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers imported from the module under test
# ---------------------------------------------------------------------------

from core.config import (
    FastStreamConfig,
    mask_amqp_url,
    _rewrite_amqp_host,
)

# ===========================================================================
# mask_amqp_url
# ===========================================================================


class TestMaskAmqpUrl:
    def test_password_is_replaced(self):
        url = "amqp://user:secret@rabbitmq:5672//"
        masked = mask_amqp_url(url)
        assert "secret" not in masked
        assert "***" in masked

    def test_username_preserved(self):
        url = "amqp://alice:hunter2@rabbitmq:5672//"
        masked = mask_amqp_url(url)
        assert "alice" in masked

    def test_host_and_port_preserved(self):
        url = "amqp://user:pw@dev.example.com:5672/myvhost"
        masked = mask_amqp_url(url)
        assert "dev.example.com" in masked
        assert "5672" in masked

    def test_vhost_preserved(self):
        url = "amqp://user:pw@host:5672/myvhost"
        masked = mask_amqp_url(url)
        assert "myvhost" in masked

    def test_no_password_unchanged(self):
        url = "amqp://host:5672//"
        assert mask_amqp_url(url) == url

    def test_amqps_scheme(self):
        url = "amqps://user:s3cr3t@broker:5671//"
        masked = mask_amqp_url(url)
        assert "s3cr3t" not in masked
        assert masked.startswith("amqps://")


# ===========================================================================
# _rewrite_amqp_host
# ===========================================================================


class TestRewriteAmqpHost:
    def test_host_replaced(self):
        url = "amqp://user:pw@old-host:1234//"
        result = _rewrite_amqp_host(url, "rabbitmq", 5672)
        assert "rabbitmq" in result
        assert "old-host" not in result

    def test_port_replaced(self):
        url = "amqp://user:pw@old-host:1234//"
        result = _rewrite_amqp_host(url, "rabbitmq", 5672)
        assert "5672" in result

    def test_credentials_preserved(self):
        url = "amqp://myuser:mypass@old-host:1234//"
        result = _rewrite_amqp_host(url, "rabbitmq", 5672)
        assert "myuser" in result
        assert "mypass" in result

    def test_vhost_preserved(self):
        url = "amqp://u:p@h:5672/vhost1"
        result = _rewrite_amqp_host(url, "rabbitmq", 5672)
        assert "vhost1" in result

    def test_no_userinfo(self):
        url = "amqp://old-host:5672//"
        result = _rewrite_amqp_host(url, "rabbitmq", 5672)
        assert "rabbitmq" in result
        assert "@" not in result.split("://", 1)[1].split("/")[0]


# ===========================================================================
# FastStreamConfig URL rewriting via model_validator
# ===========================================================================


EXTERNAL_URL = "amqp://user:pass@dev.leo4.ru:5672//"
LOCAL_RABBITMQ_URL = "amqp://user:pass@rabbitmq:5672//"
LOCALHOST_URL = "amqp://user:pass@localhost:5672//"


class TestFastStreamConfigRewrite:
    def test_external_host_rewritten_to_compose_host(self):
        cfg = FastStreamConfig(
            url=EXTERNAL_URL,
            rewrite_external_host_to_compose=True,
            compose_host="rabbitmq",
            compose_port=5672,
        )
        parsed_host = str(cfg.url).split("@")[1].split(":")[0]
        assert parsed_host == "rabbitmq"

    def test_external_host_port_rewritten(self):
        cfg = FastStreamConfig(
            url="amqp://user:pass@dev.leo4.ru:9999//",
            rewrite_external_host_to_compose=True,
            compose_host="rabbitmq",
            compose_port=5672,
        )
        assert ":5672" in str(cfg.url)

    def test_allowlisted_host_not_rewritten_rabbitmq(self):
        cfg = FastStreamConfig(
            url=LOCAL_RABBITMQ_URL,
            rewrite_external_host_to_compose=True,
        )
        assert "rabbitmq" in str(cfg.url)
        # Should not have changed anything
        assert str(cfg.url) == LOCAL_RABBITMQ_URL

    def test_allowlisted_host_not_rewritten_localhost(self):
        cfg = FastStreamConfig(
            url=LOCALHOST_URL,
            rewrite_external_host_to_compose=True,
        )
        assert "localhost" in str(cfg.url)

    def test_credentials_preserved_after_rewrite(self):
        cfg = FastStreamConfig(
            url=EXTERNAL_URL,
            rewrite_external_host_to_compose=True,
        )
        url_str = str(cfg.url)
        assert "user" in url_str
        assert "pass" in url_str

    def test_vhost_preserved_after_rewrite(self):
        cfg = FastStreamConfig(
            url="amqp://u:p@external.example.com:5672/myvhost",
            rewrite_external_host_to_compose=True,
        )
        assert "myvhost" in str(cfg.url)

    def test_rewrite_disabled(self):
        cfg = FastStreamConfig(
            url=EXTERNAL_URL,
            rewrite_external_host_to_compose=False,
        )
        assert "dev.leo4.ru" in str(cfg.url)

    def test_custom_compose_host(self):
        cfg = FastStreamConfig(
            url=EXTERNAL_URL,
            rewrite_external_host_to_compose=True,
            compose_host="my-rmq-service",
            compose_port=5673,
        )
        assert "my-rmq-service" in str(cfg.url)
        assert "5673" in str(cfg.url)

    def test_password_not_in_log_on_rewrite(self, caplog):
        import logging

        with caplog.at_level(logging.INFO, logger="core.config"):
            FastStreamConfig(
                url="amqp://admin:topsecret@external.host:5672//",
                rewrite_external_host_to_compose=True,
            )
        for record in caplog.records:
            assert "topsecret" not in record.getMessage()


# ===========================================================================
# Retry / backoff logic in create_api_app._start_broker_with_retry
# ===========================================================================

# Import lazily to avoid triggering module-level side effects during collection.


@pytest.mark.anyio
async def test_retry_succeeds_after_failures():
    """broker.start() raises twice then succeeds; total calls == 3."""
    from create_api_app import _start_broker_with_retry

    call_count = 0

    async def mock_start():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise OSError("connection refused")

    with (
        patch("create_api_app.fs_router") as mock_router,
        patch("create_api_app.settings") as mock_settings,
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        mock_router.broker.start = mock_start
        mock_settings.faststream.url = "amqp://user:pass@rabbitmq:5672//"
        mock_settings.faststream.connect_max_retries = 5
        mock_settings.faststream.connect_initial_delay = 0.1
        mock_settings.faststream.connect_max_delay = 1.0
        mock_settings.faststream.connect_backoff_factor = 2.0
        mock_settings.faststream.connect_jitter = 0.0
        mock_settings.faststream.connect_timeout = 0  # disable per-attempt timeout

        await _start_broker_with_retry()

    assert call_count == 3


@pytest.mark.anyio
async def test_retry_raises_after_exhaustion():
    """When retries are exhausted, the original exception is re-raised."""
    from create_api_app import _start_broker_with_retry

    async def always_fail():
        raise OSError("no route to host")

    with (
        patch("create_api_app.fs_router") as mock_router,
        patch("create_api_app.settings") as mock_settings,
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        mock_router.broker.start = always_fail
        mock_settings.faststream.url = "amqp://user:pass@rabbitmq:5672//"
        mock_settings.faststream.connect_max_retries = 3
        mock_settings.faststream.connect_initial_delay = 0.1
        mock_settings.faststream.connect_max_delay = 1.0
        mock_settings.faststream.connect_backoff_factor = 2.0
        mock_settings.faststream.connect_jitter = 0.0
        mock_settings.faststream.connect_timeout = 0

        with pytest.raises(OSError, match="no route to host"):
            await _start_broker_with_retry()


@pytest.mark.anyio
async def test_delay_grows_with_backoff():
    """Sleep calls should use non-decreasing delays bounded by max_delay."""
    from create_api_app import _start_broker_with_retry

    call_count = 0
    sleep_calls: list[float] = []

    async def fail_3_times():
        nonlocal call_count
        call_count += 1
        if call_count <= 3:
            raise OSError("refused")

    async def mock_sleep(delay: float):
        sleep_calls.append(delay)

    with (
        patch("create_api_app.fs_router") as mock_router,
        patch("create_api_app.settings") as mock_settings,
        patch("asyncio.sleep", side_effect=mock_sleep),
    ):
        mock_router.broker.start = fail_3_times
        mock_settings.faststream.url = "amqp://user:pass@rabbitmq:5672//"
        mock_settings.faststream.connect_max_retries = 10
        mock_settings.faststream.connect_initial_delay = 0.5
        mock_settings.faststream.connect_max_delay = 5.0
        mock_settings.faststream.connect_backoff_factor = 2.0
        mock_settings.faststream.connect_jitter = 0.0  # no jitter for determinism
        mock_settings.faststream.connect_timeout = 0

        await _start_broker_with_retry()

    # With jitter=0 the delays should be exactly 0.5, 1.0, 2.0
    assert sleep_calls == pytest.approx([0.5, 1.0, 2.0])


@pytest.mark.anyio
async def test_delay_bounded_by_max_delay():
    """Sleep delay must never exceed connect_max_delay."""
    from create_api_app import _start_broker_with_retry

    call_count = 0
    sleep_calls: list[float] = []

    async def fail_5_times():
        nonlocal call_count
        call_count += 1
        if call_count <= 5:
            raise OSError("refused")

    async def mock_sleep(delay: float):
        sleep_calls.append(delay)

    with (
        patch("create_api_app.fs_router") as mock_router,
        patch("create_api_app.settings") as mock_settings,
        patch("asyncio.sleep", side_effect=mock_sleep),
    ):
        mock_router.broker.start = fail_5_times
        mock_settings.faststream.url = "amqp://user:pass@rabbitmq:5672//"
        mock_settings.faststream.connect_max_retries = 10
        mock_settings.faststream.connect_initial_delay = 1.0
        mock_settings.faststream.connect_max_delay = 3.0
        mock_settings.faststream.connect_backoff_factor = 2.0
        mock_settings.faststream.connect_jitter = 0.0
        mock_settings.faststream.connect_timeout = 0

        await _start_broker_with_retry()

    for d in sleep_calls:
        assert d <= 3.0
