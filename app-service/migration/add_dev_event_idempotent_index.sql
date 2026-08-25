-- ============================================================
-- EVA idempotency: partial unique index on tb_dev_events
-- Ensures that (device_id, dev_event_id, dev_timestamp) is unique
-- for all events where dev_event_id != 0.
-- Events with dev_event_id = 0 are fire-and-forget (no dedup).
--
-- dev_timestamp включён в индекс, чтобы не терять события при
-- гонках или сбросе счётчика dev_event_id на устройстве.
-- ============================================================

BEGIN;

-- 1. Удаляем существующие дубликаты, оставляя только самую свежую запись (max id)
DELETE FROM tb_dev_events e
USING (
    SELECT device_id, dev_event_id, dev_timestamp, MAX(id) AS keep_id
    FROM tb_dev_events
    WHERE dev_event_id != 0
    GROUP BY device_id, dev_event_id, dev_timestamp
    HAVING COUNT(*) > 1
) dups
WHERE e.device_id = dups.device_id
  AND e.dev_event_id = dups.dev_event_id
  AND e.dev_timestamp = dups.dev_timestamp
  AND e.id != dups.keep_id
  AND e.dev_event_id != 0;

-- 2. Создание частичного уникального индекса
CREATE UNIQUE INDEX IF NOT EXISTS uq_dev_event_idempotent
    ON tb_dev_events (device_id, dev_event_id, dev_timestamp)
    WHERE dev_event_id != 0;

COMMIT;

-- ============================================================
-- Откат (при необходимости):
-- DROP INDEX IF EXISTS uq_dev_event_idempotent;
-- ============================================================

