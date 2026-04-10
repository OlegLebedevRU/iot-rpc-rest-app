-- Billing: coefficients table
-- Stores K1–K4 coefficients with effective_from date.
-- Only one row per effective_from date is allowed.
CREATE TABLE IF NOT EXISTS tb_billing_coefficients (
    id              SERIAL PRIMARY KEY,
    k1              NUMERIC(12, 6) NOT NULL DEFAULT 10000,
    k2              NUMERIC(12, 6) NOT NULL DEFAULT 1,
    k3              NUMERIC(12, 6) NOT NULL DEFAULT 1,
    k4              NUMERIC(12, 6) NOT NULL DEFAULT 1,
    effective_from  DATE NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_billing_coefficients_effective_from UNIQUE (effective_from)
);

-- Seed default coefficients row (effective from the beginning of time)
INSERT INTO tb_billing_coefficients (k1, k2, k3, k4, effective_from)
VALUES (10000, 1, 1, 1, '2020-01-01')
ON CONFLICT (effective_from) DO NOTHING;

-- Billing: counters table
-- Accumulates per-org usage counters for each billing period.
CREATE TABLE IF NOT EXISTS tb_billing_counters (
    id                  SERIAL PRIMARY KEY,
    org_id              INTEGER NOT NULL,
    period_start        DATE NOT NULL,
    period_end          DATE NOT NULL,
    active_devices      INTEGER NOT NULL DEFAULT 0,
    api_requests        BIGINT NOT NULL DEFAULT 0,
    evt_messages        BIGINT NOT NULL DEFAULT 0,
    res_messages        BIGINT NOT NULL DEFAULT 0,
    res_payload_blocks  BIGINT NOT NULL DEFAULT 0,
    consumption         NUMERIC(18, 4),
    calculated_at       TIMESTAMPTZ,
    CONSTRAINT uq_billing_counters_org_period UNIQUE (org_id, period_start)
);

CREATE INDEX IF NOT EXISTS ix_billing_counters_period_start ON tb_billing_counters (period_start);

-- Billing: active devices tracking
-- Tracks which devices had activity during a billing period (for P1 calculation).
CREATE TABLE IF NOT EXISTS tb_billing_active_devices (
    id              SERIAL PRIMARY KEY,
    org_id          INTEGER NOT NULL,
    period_start    DATE NOT NULL,
    device_id       INTEGER NOT NULL,
    CONSTRAINT uq_billing_active_device UNIQUE (org_id, period_start, device_id)
);

CREATE INDEX IF NOT EXISTS ix_billing_active_devices_period ON tb_billing_active_devices (org_id, period_start);
