-- ============================================================
-- Cleanup old events from tb_dev_events (retention: 30 days)
--
-- Run via SSH on production (87.242.100.34):
--   scp -i "d:\.ssh\id_ed25519" \
--     app-service/scripts/cleanup_old_events.sql \
--     user1@87.242.100.34:/home/user1/iot-rpc-rest-app/
--   ssh -n -i "d:\.ssh\id_ed25519" user1@87.242.100.34 \
--     "psql -h 10.0.0.7 -U leo4_db_user -d iot_rpc \
--      -f /home/user1/iot-rpc-rest-app/cleanup_old_events.sql"
-- ============================================================

\set ON_ERROR_STOP on

-- ── STEP 1: Diagnostics (before cleanup) ──────────────────────

\echo ''
\echo '=== STEP 1: Diagnostics (before cleanup) ==='
\echo ''

SELECT pg_size_pretty(pg_total_relation_size('tb_dev_events')) AS table_size_before;

SELECT count(*) AS total_events FROM tb_dev_events;

SELECT count(*) AS events_to_delete
FROM tb_dev_events
WHERE created_at < now() - interval '30 days';

SELECT min(created_at) AS oldest_event,
       max(created_at) AS newest_event
FROM tb_dev_events;

SELECT count(*) AS devices_with_offsets FROM tb_device_event_offsets;

-- ── STEP 2: Batch delete events older than 30 days ────────────
-- Uses a PROCEDURE so we can COMMIT between batches and avoid
-- long-held locks.  Each batch deletes 10 000 rows, then sleeps
-- 0.5 s to let other transactions proceed.

\echo ''
\echo '=== STEP 2: Batch delete events older than 30 days ==='
\echo ''

CREATE OR REPLACE PROCEDURE cleanup_old_events_proc()
LANGUAGE plpgsql
AS $$
DECLARE
    batch_size  int := 10000;
    deleted     int := 1;
    total_del   int := 0;
    cutoff      timestamptz := now() - interval '30 days';
BEGIN
    RAISE NOTICE 'Cutoff date: %', cutoff;

    WHILE deleted > 0 LOOP
        DELETE FROM tb_dev_events
        WHERE id IN (
            SELECT id FROM tb_dev_events
            WHERE created_at < cutoff
            ORDER BY id
            LIMIT batch_size
        );
        GET DIAGNOSTICS deleted = ROW_COUNT;
        total_del := total_del + deleted;

        IF deleted > 0 THEN
            RAISE NOTICE 'Batch deleted: % rows (total: %)', deleted, total_del;
            COMMIT;
            PERFORM pg_sleep(0.5);
        END IF;
    END LOOP;

    RAISE NOTICE 'Delete phase complete. Total deleted: %', total_del;
END;
$$;

CALL cleanup_old_events_proc();

-- Clean up the helper procedure
DROP PROCEDURE IF EXISTS cleanup_old_events_proc;

-- ── STEP 3: Reset device event offsets ────────────────────────

\echo ''
\echo '=== STEP 3: Reset device event offsets ==='
\echo ''

UPDATE tb_device_event_offsets
SET last_event_id = 0,
    updated_at = now();

SELECT count(*) AS offsets_reset FROM tb_device_event_offsets;

-- ── STEP 4: VACUUM to reclaim disk space ──────────────────────

\echo ''
\echo '=== STEP 4: VACUUM (reclaim disk space) ==='
\echo ''

VACUUM (VERBOSE, ANALYZE) tb_dev_events;

-- ── STEP 5: Diagnostics (after cleanup) ───────────────────────

\echo ''
\echo '=== STEP 5: Diagnostics (after cleanup) ==='
\echo ''

SELECT pg_size_pretty(pg_total_relation_size('tb_dev_events')) AS table_size_after;

SELECT count(*) AS remaining_events FROM tb_dev_events;

SELECT min(created_at) AS oldest_remaining,
       max(created_at) AS newest_remaining
FROM tb_dev_events;

\echo ''
\echo '=== Cleanup complete ==='
