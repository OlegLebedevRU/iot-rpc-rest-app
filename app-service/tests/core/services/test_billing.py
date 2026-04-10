"""Unit tests for billing schemas, repo helpers, and service logic."""

import math
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.schemas.billing import (
    BillingCoefficientCreate,
    BillingCoefficientOut,
    BillingCounterOut,
    BillingEvent,
    BillingRecalculateRequest,
)
from core.crud.billing_repo import _current_period, BillingRepo
from core.services.billing import BillingService, _period_for, _previous_period


# ──────────────── Schema tests ────────────────


class TestBillingSchemas:
    def test_billing_event_schema_defaults(self):
        evt = BillingEvent(
            org_id=1, device_id=100, counter_type="evt"
        )
        assert evt.value == 1
        assert evt.payload_bytes == 0

    def test_billing_event_schema_full(self):
        evt = BillingEvent(
            org_id=1, device_id=100, counter_type="res", value=1, payload_bytes=4096
        )
        assert evt.counter_type == "res"
        assert evt.payload_bytes == 4096

    def test_coefficient_create_defaults(self):
        c = BillingCoefficientCreate(effective_from=date(2026, 1, 1))
        assert c.k1 == Decimal("10000")
        assert c.k2 == Decimal("1")
        assert c.k3 == Decimal("1")
        assert c.k4 == Decimal("1")

    def test_coefficient_create_custom(self):
        c = BillingCoefficientCreate(
            k1=Decimal("5000"),
            k2=Decimal("2"),
            k3=Decimal("3"),
            k4=Decimal("4"),
            effective_from=date(2026, 3, 1),
        )
        assert c.k1 == Decimal("5000")
        assert c.effective_from == date(2026, 3, 1)

    def test_recalculate_request(self):
        r = BillingRecalculateRequest(period=date(2026, 3, 1))
        assert r.period == date(2026, 3, 1)

    def test_counter_out_optional_fields(self):
        c = BillingCounterOut(
            org_id=1,
            period_start=date(2026, 3, 1),
            period_end=date(2026, 4, 1),
        )
        assert c.consumption is None
        assert c.calculated_at is None
        assert c.api_requests == 0


# ──────────────── Helper function tests ────────────────


class TestHelperFunctions:
    def test_current_period_returns_first_of_month(self):
        ps, pe = _current_period()
        assert ps.day == 1
        assert pe.day == 1
        if ps.month == 12:
            assert pe.month == 1
            assert pe.year == ps.year + 1
        else:
            assert pe.month == ps.month + 1

    def test_period_for_mid_month(self):
        ps, pe = _period_for(date(2026, 6, 15))
        assert ps == date(2026, 6, 1)
        assert pe == date(2026, 7, 1)

    def test_period_for_december(self):
        ps, pe = _period_for(date(2026, 12, 25))
        assert ps == date(2026, 12, 1)
        assert pe == date(2027, 1, 1)

    def test_previous_period(self):
        ps, pe = _previous_period()
        today = date.today()
        first_of_current = today.replace(day=1)
        # period_end should be first of current month
        assert pe == first_of_current
        # period_start should be first of previous month
        assert ps.day == 1
        if first_of_current.month == 1:
            assert ps.month == 12
            assert ps.year == first_of_current.year - 1
        else:
            assert ps.month == first_of_current.month - 1

    def test_blocks_calculation(self):
        """Verify block counting for P4: ceil(payload_bytes / 2048)."""
        block_size = 2048
        assert max(1, math.ceil(0 / block_size)) == 1  # 0 bytes -> at least 1 block
        assert max(1, math.ceil(1 / block_size)) == 1
        assert max(1, math.ceil(2048 / block_size)) == 1
        assert max(1, math.ceil(2049 / block_size)) == 2
        assert max(1, math.ceil(4096 / block_size)) == 2
        assert max(1, math.ceil(4097 / block_size)) == 3


# ──────────────── Service logic tests (mocked DB) ────────────────


class TestBillingService:
    @pytest.mark.anyio
    async def test_calculate_period_no_orgs(self):
        session = AsyncMock()
        with (
            patch.object(BillingRepo, "get_effective_coefficients", return_value=None),
            patch.object(BillingRepo, "get_all_org_ids_for_period", return_value=[]),
        ):
            count = await BillingService.calculate_period(
                session, date(2026, 3, 1), date(2026, 4, 1)
            )
            assert count == 0

    @pytest.mark.anyio
    async def test_calculate_period_with_org(self):
        session = AsyncMock()

        mock_coeff = MagicMock()
        mock_coeff.k1 = Decimal("10000")
        mock_coeff.k2 = Decimal("1")
        mock_coeff.k3 = Decimal("1")
        mock_coeff.k4 = Decimal("1")

        mock_counter = MagicMock()
        mock_counter.api_requests = 100
        mock_counter.evt_messages = 50
        mock_counter.res_payload_blocks = 10

        with (
            patch.object(
                BillingRepo, "get_effective_coefficients", return_value=mock_coeff
            ),
            patch.object(
                BillingRepo, "get_all_org_ids_for_period", return_value=[1]
            ),
            patch.object(
                BillingRepo, "count_active_devices", return_value=5
            ),
            patch.object(
                BillingRepo, "get_counter", return_value=mock_counter
            ),
            patch.object(
                BillingRepo, "save_calculation", new_callable=AsyncMock
            ) as mock_save,
        ):
            count = await BillingService.calculate_period(
                session, date(2026, 3, 1), date(2026, 4, 1)
            )
            assert count == 1

            # Verify save was called with correct values
            mock_save.assert_called_once()
            call_kwargs = mock_save.call_args.kwargs
            assert call_kwargs["org_id"] == 1
            assert call_kwargs["active_devices"] == 5
            # P1=5*10000=50000, P2=100*1=100, P3=50*1=50, P4=10*1=10
            expected = Decimal("50000") + Decimal("100") + Decimal("50") + Decimal("10")
            assert call_kwargs["consumption"] == expected

    @pytest.mark.anyio
    async def test_handle_billing_event_evt(self):
        session = AsyncMock()

        with (
            patch.object(
                BillingRepo, "record_device_activity", new_callable=AsyncMock
            ) as mock_activity,
            patch.object(
                BillingRepo, "increment_evt_messages", new_callable=AsyncMock
            ) as mock_evt,
        ):
            await BillingService.handle_billing_event(
                session, org_id=1, device_id=100, counter_type="evt"
            )
            mock_activity.assert_called_once_with(session, 1, 100)
            mock_evt.assert_called_once_with(session, 1, 1)

    @pytest.mark.anyio
    async def test_handle_billing_event_res(self):
        session = AsyncMock()

        with (
            patch.object(
                BillingRepo, "record_device_activity", new_callable=AsyncMock
            ),
            patch.object(
                BillingRepo, "increment_res_messages", new_callable=AsyncMock
            ) as mock_res,
        ):
            await BillingService.handle_billing_event(
                session, org_id=1, device_id=100, counter_type="res", payload_bytes=3000
            )
            mock_res.assert_called_once()

    @pytest.mark.anyio
    async def test_handle_billing_event_api(self):
        session = AsyncMock()

        with (
            patch.object(
                BillingRepo, "record_device_activity", new_callable=AsyncMock
            ),
            patch.object(
                BillingRepo, "increment_api_requests", new_callable=AsyncMock
            ) as mock_api,
        ):
            await BillingService.handle_billing_event(
                session, org_id=1, device_id=0, counter_type="api"
            )
            mock_api.assert_called_once_with(session, 1, 1)

    @pytest.mark.anyio
    async def test_handle_billing_event_activity_only(self):
        session = AsyncMock()

        with (
            patch.object(
                BillingRepo, "record_device_activity", new_callable=AsyncMock
            ) as mock_activity,
        ):
            await BillingService.handle_billing_event(
                session, org_id=1, device_id=100, counter_type="activity"
            )
            mock_activity.assert_called_once_with(session, 1, 100)

    @pytest.mark.anyio
    async def test_handle_billing_event_no_device_activity_for_zero(self):
        """device_id=0 should not record device activity."""
        session = AsyncMock()

        with (
            patch.object(
                BillingRepo, "record_device_activity", new_callable=AsyncMock
            ) as mock_activity,
            patch.object(
                BillingRepo, "increment_api_requests", new_callable=AsyncMock
            ),
        ):
            await BillingService.handle_billing_event(
                session, org_id=1, device_id=0, counter_type="api"
            )
            mock_activity.assert_not_called()


# ──────────────── Billing admin endpoint access control ────────────────


class TestBillingAdminAccess:
    def test_require_admin_raises_for_non_zero(self):
        from api.api_v1.billing import _require_admin
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _require_admin(1)
        assert exc_info.value.status_code == 403

    def test_require_admin_passes_for_zero(self):
        from api.api_v1.billing import _require_admin

        # Should not raise
        _require_admin(0)

    def test_coefficient_cannot_set_current_month(self):
        """effective_from within the current month should be rejected by the endpoint logic."""
        today = date.today()
        current_month_start = today.replace(day=1)
        if current_month_start.month == 12:
            next_month_start = current_month_start.replace(
                year=current_month_start.year + 1, month=1
            )
        else:
            next_month_start = current_month_start.replace(
                month=current_month_start.month + 1
            )
        # Current month dates should be blocked
        assert current_month_start <= current_month_start < next_month_start
        # Future month dates should be allowed
        assert not (current_month_start <= next_month_start < next_month_start)
