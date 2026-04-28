"""
Unit tests for the webhook dispatch flow in internal_bus.webhooks().

All external I/O (DB session, HTTP client) is mocked so no live services
are required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import core.topologys.internal_bus as ib_module
from core.topologys.internal_bus import webhooks

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_msg(
    msg_type: str | None,
    device_id: str | None,
    body: bytes = b"{}",
    correlation_id: str = "corr-1",
):
    """Build a minimal fake RabbitMessage for testing.

    Args:
        msg_type: Value for the ``x-msg-type`` header; omitted when ``None``.
        device_id: Value for the ``x-device-id`` header; omitted when ``None``.
        body: Raw message body bytes (default: ``b"{}"``).
        correlation_id: Correlation ID string (default: ``"corr-1"``).

    Returns:
        MagicMock: Mocked RabbitMessage with the requested headers set.
    """
    raw_headers: dict = {}
    if msg_type is not None:
        raw_headers["x-msg-type"] = msg_type
    if device_id is not None:
        raw_headers["x-device-id"] = device_id

    msg = MagicMock()
    msg.raw_message.headers = raw_headers
    msg.headers = raw_headers
    msg.body = body
    msg.correlation_id = correlation_id
    return msg


def _make_webhook_obj(
    org_id: int,
    event_type: str = "msg-event",
    url: str = "https://example.com/hook",
    headers: dict | None = None,
    is_active: bool = True,
):
    wh = MagicMock()
    wh.id = 1
    wh.org_id = org_id
    wh.event_type = event_type
    wh.url = url
    wh.headers = headers
    wh.is_active = is_active
    return wh


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestWebhookDispatchEarlyExits:
    @pytest.mark.anyio
    async def test_no_msg_type_header_returns_early(self):
        session = AsyncMock()
        msg = _make_msg(msg_type=None, device_id="100")

        with patch.object(ib_module.DeviceRepo, "get_org_id_by_device_id") as mock_org:
            await webhooks(session, msg)
            mock_org.assert_not_called()

    @pytest.mark.anyio
    async def test_no_device_id_header_returns_early(self):
        session = AsyncMock()
        msg = _make_msg(msg_type="msg-event", device_id=None)

        with patch.object(ib_module.DeviceRepo, "get_org_id_by_device_id") as mock_org:
            await webhooks(session, msg)
            mock_org.assert_not_called()

    @pytest.mark.anyio
    async def test_non_numeric_device_id_returns_early(self):
        session = AsyncMock()
        msg = _make_msg(msg_type="msg-event", device_id="not-a-number")

        with patch.object(ib_module.DeviceRepo, "get_org_id_by_device_id") as mock_org:
            await webhooks(session, msg)
            mock_org.assert_not_called()

    @pytest.mark.anyio
    async def test_unresolvable_org_id_returns_early(self):
        session = AsyncMock()
        msg = _make_msg(msg_type="msg-event", device_id="9999")

        with (
            patch.object(
                ib_module.DeviceRepo,
                "get_org_id_by_device_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch.object(ib_module.WebhookRepo, "get_by_org_and_type") as mock_wh,
        ):
            await webhooks(session, msg)
            mock_wh.assert_not_called()

    @pytest.mark.anyio
    async def test_no_webhook_row_returns_early(self):
        session = AsyncMock()
        msg = _make_msg(msg_type="msg-event", device_id="9999")

        with (
            patch.object(
                ib_module.DeviceRepo,
                "get_org_id_by_device_id",
                new_callable=AsyncMock,
                return_value=7,
            ),
            patch.object(
                ib_module.WebhookRepo,
                "get_by_org_and_type",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            mock_send = AsyncMock()
            with patch(
                "core.topologys.internal_bus.Webhook", autospec=True
            ) as mock_cls:
                mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_send)
                mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
                await webhooks(session, msg)
                mock_cls.assert_not_called()

    @pytest.mark.anyio
    async def test_inactive_webhook_returns_early(self):
        session = AsyncMock()
        msg = _make_msg(msg_type="msg-event", device_id="9999")
        webhook_obj = _make_webhook_obj(org_id=7, is_active=False)

        with (
            patch.object(
                ib_module.DeviceRepo,
                "get_org_id_by_device_id",
                new_callable=AsyncMock,
                return_value=7,
            ),
            patch.object(
                ib_module.WebhookRepo,
                "get_by_org_and_type",
                new_callable=AsyncMock,
                return_value=webhook_obj,
            ),
        ):
            mock_send = AsyncMock()
            with patch(
                "core.topologys.internal_bus.Webhook", autospec=True
            ) as mock_cls:
                mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_send)
                mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
                await webhooks(session, msg)
                mock_cls.assert_not_called()


class TestWebhookDispatchHappyPath:
    @pytest.mark.anyio
    async def test_msg_event_sends_to_correct_org(self):
        """Full happy-path: device_id -> org_id -> webhook -> send."""
        session = AsyncMock()
        msg = _make_msg(msg_type="msg-event", device_id="9993", body=b'{"k": "v"}')
        webhook_obj = _make_webhook_obj(org_id=4, url="https://example.com/hook")

        mock_wh_instance = AsyncMock()
        mock_wh_instance.send = AsyncMock()

        with (
            patch.object(
                ib_module.DeviceRepo,
                "get_org_id_by_device_id",
                new_callable=AsyncMock,
                return_value=4,
            ),
            patch.object(
                ib_module.WebhookRepo,
                "get_by_org_and_type",
                new_callable=AsyncMock,
                return_value=webhook_obj,
            ),
            patch("core.topologys.internal_bus.Webhook") as mock_cls,
        ):
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_wh_instance)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await webhooks(session, msg)

            # Verify device_id resolved to the correct org
            ib_module.DeviceRepo.get_org_id_by_device_id.assert_awaited_once_with(
                session, device_id=9993
            )
            # Verify webhook lookup used the resolved org_id, not 0
            ib_module.WebhookRepo.get_by_org_and_type.assert_awaited_once_with(
                4, "msg-event"
            )
            # Verify send was called
            mock_wh_instance.send.assert_awaited_once_with({"k": "v"})

    @pytest.mark.anyio
    async def test_headers_empty_dict_does_not_block_dispatch(self):
        """headers={} must be treated identically to headers=None."""
        session = AsyncMock()
        msg = _make_msg(msg_type="msg-event", device_id="42")
        # Webhook with empty dict headers (not null)
        webhook_obj = _make_webhook_obj(org_id=5, headers={})

        mock_wh_instance = AsyncMock()
        mock_wh_instance.send = AsyncMock()

        with (
            patch.object(
                ib_module.DeviceRepo,
                "get_org_id_by_device_id",
                new_callable=AsyncMock,
                return_value=5,
            ),
            patch.object(
                ib_module.WebhookRepo,
                "get_by_org_and_type",
                new_callable=AsyncMock,
                return_value=webhook_obj,
            ),
            patch("core.topologys.internal_bus.Webhook") as mock_cls,
        ):
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_wh_instance)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await webhooks(session, msg)

            mock_wh_instance.send.assert_awaited_once()

    @pytest.mark.anyio
    async def test_headers_null_does_not_block_dispatch(self):
        """headers=None must not block dispatch."""
        session = AsyncMock()
        msg = _make_msg(msg_type="msg-event", device_id="42")
        webhook_obj = _make_webhook_obj(org_id=5, headers=None)

        mock_wh_instance = AsyncMock()
        mock_wh_instance.send = AsyncMock()

        with (
            patch.object(
                ib_module.DeviceRepo,
                "get_org_id_by_device_id",
                new_callable=AsyncMock,
                return_value=5,
            ),
            patch.object(
                ib_module.WebhookRepo,
                "get_by_org_and_type",
                new_callable=AsyncMock,
                return_value=webhook_obj,
            ),
            patch("core.topologys.internal_bus.Webhook") as mock_cls,
        ):
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_wh_instance)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await webhooks(session, msg)

            mock_wh_instance.send.assert_awaited_once()

    @pytest.mark.anyio
    async def test_msg_event_path_suffix_uses_device_id(self):
        """For msg-event, path_suffix must be /<device_id>."""
        session = AsyncMock()
        msg = _make_msg(
            msg_type="msg-event", device_id="77", correlation_id="should-not-be-used"
        )
        webhook_obj = _make_webhook_obj(org_id=3, url="https://example.com/hook")

        mock_wh_instance = AsyncMock()
        mock_wh_instance.send = AsyncMock()

        with (
            patch.object(
                ib_module.DeviceRepo,
                "get_org_id_by_device_id",
                new_callable=AsyncMock,
                return_value=3,
            ),
            patch.object(
                ib_module.WebhookRepo,
                "get_by_org_and_type",
                new_callable=AsyncMock,
                return_value=webhook_obj,
            ),
            patch("core.topologys.internal_bus.Webhook") as mock_cls,
        ):
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_wh_instance)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await webhooks(session, msg)

            # Webhook should have been constructed with path_suffix="/77"
            call_kwargs = mock_cls.call_args.kwargs
            assert call_kwargs["path_suffix"] == "/77"

    @pytest.mark.anyio
    async def test_msg_task_result_path_suffix_uses_correlation_id(self):
        """For msg-task-result, path_suffix must be /<correlation_id>."""
        session = AsyncMock()
        msg = _make_msg(
            msg_type="msg-task-result", device_id="77", correlation_id="corr-xyz"
        )
        webhook_obj = _make_webhook_obj(
            org_id=3, event_type="msg-task-result", url="https://example.com/hook"
        )

        mock_wh_instance = AsyncMock()
        mock_wh_instance.send = AsyncMock()

        with (
            patch.object(
                ib_module.DeviceRepo,
                "get_org_id_by_device_id",
                new_callable=AsyncMock,
                return_value=3,
            ),
            patch.object(
                ib_module.WebhookRepo,
                "get_by_org_and_type",
                new_callable=AsyncMock,
                return_value=webhook_obj,
            ),
            patch("core.topologys.internal_bus.Webhook") as mock_cls,
        ):
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_wh_instance)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await webhooks(session, msg)

            call_kwargs = mock_cls.call_args.kwargs
            assert call_kwargs["path_suffix"] == "/corr-xyz"


class TestWebhookDispatchSendError:
    @pytest.mark.anyio
    async def test_send_exception_is_caught_and_logged(self):
        """If wh.send() raises, the handler must not propagate the exception."""
        session = AsyncMock()
        msg = _make_msg(msg_type="msg-event", device_id="42")
        webhook_obj = _make_webhook_obj(org_id=5)

        mock_wh_instance = AsyncMock()
        mock_wh_instance.send = AsyncMock(side_effect=Exception("network error"))

        with (
            patch.object(
                ib_module.DeviceRepo,
                "get_org_id_by_device_id",
                new_callable=AsyncMock,
                return_value=5,
            ),
            patch.object(
                ib_module.WebhookRepo,
                "get_by_org_and_type",
                new_callable=AsyncMock,
                return_value=webhook_obj,
            ),
            patch("core.topologys.internal_bus.Webhook") as mock_cls,
        ):
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_wh_instance)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            # Must not raise
            await webhooks(session, msg)


class TestWebhookHeadersMerge:
    @pytest.mark.anyio
    async def test_webhook_headers_merged_with_transport_headers(self):
        """Custom headers from the webhook record are preserved alongside transport headers."""
        session = AsyncMock()
        msg = _make_msg(msg_type="msg-event", device_id="55")
        webhook_obj = _make_webhook_obj(
            org_id=6,
            headers={"Authorization": "Bearer secret"},
        )

        mock_wh_instance = AsyncMock()
        mock_wh_instance.send = AsyncMock()

        with (
            patch.object(
                ib_module.DeviceRepo,
                "get_org_id_by_device_id",
                new_callable=AsyncMock,
                return_value=6,
            ),
            patch.object(
                ib_module.WebhookRepo,
                "get_by_org_and_type",
                new_callable=AsyncMock,
                return_value=webhook_obj,
            ),
            patch("core.topologys.internal_bus.Webhook") as mock_cls,
        ):
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_wh_instance)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await webhooks(session, msg)

            call_kwargs = mock_cls.call_args.kwargs
            sent_headers = call_kwargs["headers"]
            assert sent_headers.get("Authorization") == "Bearer secret"
            assert sent_headers.get("x-msg-type") == "msg-event"
            assert sent_headers.get("x-device-id") == "55"

    @pytest.mark.anyio
    async def test_empty_dict_headers_only_transport_headers_present(self):
        """headers={} results in only transport headers in the outgoing request."""
        session = AsyncMock()
        msg = _make_msg(msg_type="msg-event", device_id="55")
        webhook_obj = _make_webhook_obj(org_id=6, headers={})

        mock_wh_instance = AsyncMock()
        mock_wh_instance.send = AsyncMock()

        with (
            patch.object(
                ib_module.DeviceRepo,
                "get_org_id_by_device_id",
                new_callable=AsyncMock,
                return_value=6,
            ),
            patch.object(
                ib_module.WebhookRepo,
                "get_by_org_and_type",
                new_callable=AsyncMock,
                return_value=webhook_obj,
            ),
            patch("core.topologys.internal_bus.Webhook") as mock_cls,
        ):
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_wh_instance)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await webhooks(session, msg)

            call_kwargs = mock_cls.call_args.kwargs
            sent_headers = call_kwargs["headers"]
            assert sent_headers == {"x-msg-type": "msg-event", "x-device-id": "55"}
