-- ============================================================
-- Cleanup old tasks from tb_dev_tasks and related tables
-- (retention: 30 days)
--
-- Tables (FK order for deletion):
--   tb_dev_task_results   → FK tb_dev_tasks.id
--   tb_dev_task_payloads  → FK tb_dev_tasks.id
--   tb_dev_tasks_status   → FK tb_dev_tasks.id
--   tb_dev_tasks          ← parent
--
-- Run on production (87.242.100.34):
--   scp -i "d:\.ssh\id_ed25519" cleanup_old_tasks.sql user1@87.242.100.34:/home/user1/iot-rpc-rest-app/
--   ssh -n -i "d:\.ssh\id_ed25519" user1@87.242.100.34 \
--     "psql -h 10.0.0.7 -U leo4_db_user -d iot_rpc \
--      -f /home/user1/iot-rpc-rest-app/cleanup_old_tasks.sql"
-- ============================================================

\set ON_ERROR_STOP on

-- ── STEP 1: Diagnostics (before cleanup) ──────────────────────

\echo ''
\echo '=== STEP 1: Diagnostics (before cleanup) ==='
\echo ''

SELECT 'tb_dev_tasks' AS tbl,
       pg_size_pretty(pg_total_relation_size('tb_dev_tasks')) AS size,
       (SELECT count(*) FROM tb_dev_tasks) AS total,
       (SELECT count(*) FROM tb_dev_tasks WHERE created_at < now() - interval '30 days') AS to_delete
UNION ALL
SELECT 'tb_dev_task_payloads',
       pg_size_pretty(pg_total_relation_size('tb_dev_task_payloads')),
       (SELECT count(*) FROM tb_dev_task_payloads),
       (SELECT count(*) FROM tb_dev_task_payloads p
        WHERE p.task_id IN (SELECT id FROM tb_dev_tasks WHERE created_at < now() - interval '30 days'))
UNION ALL
SELECT 'tb_dev_tasks_status',
       pg_size_pretty(pg_total_relation_size('tb_dev_tasks_status')),
       (SELECT count(*) FROM tb_dev_tasks_status),
       (SELECT count(*) FROM tb_dev_tasks_status s
        WHERE s.task_id IN (SELECT id FROM tb_dev_tasks WHERE created_at < now() - interval '30 days'))
UNION ALL
SELECT 'tb_dev_task_results',
       pg_size_pretty(pg_total_relation_size('tb_dev_task_results')),
       (SELECT count(*) FROM tb_dev_task_results),
       (SELECT count(*) FROM tb_dev_task_results r
        WHERE r.task_id IN (SELECT id FROM tb_dev_tasks WHERE created_at < now() - interval '30 days'));

SELECT min(created_at) AS oldest_task,
       max(created_at) AS newest_task
FROM tb_dev_tasks;

-- ── STEP 2: Batch delete (children first, then parent) ───────

\echo ''
\echo '=== STEP 2: Batch delete tasks older than 30 days ==='
\echo ''

CREATE OR REPLACE PROCEDURE cleanup_old_tasks_proc()
LANGUAGE plpgsql
AS $$
DECLARE
    batch_size  int := 10000;
    cutoff      timestamptz := now() - interval '30 days';
    del         int := 1;
    total       int := 0;
BEGIN
    RAISE NOTICE 'Cutoff date: %', cutoff;

    -- 2a. Delete tb_dev_task_results (children)
    del := 1; total := 0;
    WHILE del > 0 LOOP
        DELETE FROM tb_dev_task_results
        WHERE id IN (
            SELECT r.id FROM tb_dev_task_results r
            JOIN tb_dev_tasks t ON t.id = r.task_id
            WHERE t.created_at < cutoff
            LIMIT batch_size
        );
        GET DIAGNOSTICS del = ROW_COUNT;
        total := total + del;
        IF del > 0 THEN
            RAISE NOTICE '[results] Deleted % rows (total: %)', del, total;
            COMMIT;
            PERFORM pg_sleep(0.3);
        END IF;
    END LOOP;
    RAISE NOTICE '[results] Done. Total deleted: %', total;

    -- 2b. Delete tb_dev_task_payloads (children)
    del := 1; total := 0;
    WHILE del > 0 LOOP
        DELETE FROM tb_dev_task_payloads
        WHERE id IN (
            SELECT p.id FROM tb_dev_task_payloads p
            JOIN tb_dev_tasks t ON t.id = p.task_id
            WHERE t.created_at < cutoff
            LIMIT batch_size
        );
        GET DIAGNOSTICS del = ROW_COUNT;
        total := total + del;
        IF del > 0 THEN
            RAISE NOTICE '[payloads] Deleted % rows (total: %)', del, total;
            COMMIT;
            PERFORM pg_sleep(0.3);
        END IF;
    END LOOP;
    RAISE NOTICE '[payloads] Done. Total deleted: %', total;

    -- 2c. Delete tb_dev_tasks_status (children)
    del := 1; total := 0;
    WHILE del > 0 LOOP
        DELETE FROM tb_dev_tasks_status
        WHERE id IN (
            SELECT s.id FROM tb_dev_tasks_status s
            JOIN tb_dev_tasks t ON t.id = s.task_id
            WHERE t.created_at < cutoff
            LIMIT batch_size
        );
        GET DIAGNOSTICS del = ROW_COUNT;
        total := total + del;
        IF del > 0 THEN
            RAISE NOTICE '[status] Deleted % rows (total: %)', del, total;
            COMMIT;
            PERFORM pg_sleep(0.3);
        END IF;
    END LOOP;
    RAISE NOTICE '[status] Done. Total deleted: %', total;

    -- 2d. Delete tb_dev_tasks (parent)
    del := 1; total := 0;
    WHILE del > 0 LOOP
        DELETE FROM tb_dev_tasks
        WHERE id IN (
            SELECT id FROM tb_dev_tasks
            WHERE created_at < cutoff
            LIMIT batch_size
        );
        GET DIAGNOSTICS del = ROW_COUNT;
        total := total + del;
        IF del > 0 THEN
            RAISE NOTICE '[tasks] Deleted % rows (total: %)', del, total;
            COMMIT;
            PERFORM pg_sleep(0.3);
        END IF;
    END LOOP;
    RAISE NOTICE '[tasks] Done. Total deleted: %', total;
END;
$$;

CALL cleanup_old_tasks_proc();
DROP PROCEDURE IF EXISTS cleanup_old_tasks_proc;

-- ── STEP 3: VACUUM ───────────────────────────────────────────

\echo ''
\echo '=== STEP 3: VACUUM (reclaim disk space) ==='
\echo ''

VACUUM (FULL, VERBOSE, ANALYZE) tb_dev_task_results;
VACUUM (FULL, VERBOSE, ANALYZE) tb_dev_task_payloads;
VACUUM (FULL, VERBOSE, ANALYZE) tb_dev_tasks_status;
VACUUM (FULL, VERBOSE, ANALYZE) tb_dev_tasks;

-- ── STEP 4: Diagnostics (after cleanup) ───────────────────────

\echo ''
\echo '=== STEP 4: Diagnostics (after cleanup) ==='
\echo ''

SELECT 'tb_dev_tasks' AS tbl,
       pg_size_pretty(pg_total_relation_size('tb_dev_tasks')) AS size,
       (SELECT count(*) FROM tb_dev_tasks) AS remaining
UNION ALL
SELECT 'tb_dev_task_payloads',
       pg_size_pretty(pg_total_relation_size('tb_dev_task_payloads')),
       (SELECT count(*) FROM tb_dev_task_payloads)
UNION ALL
SELECT 'tb_dev_tasks_status',
       pg_size_pretty(pg_total_relation_size('tb_dev_tasks_status')),
       (SELECT count(*) FROM tb_dev_tasks_status)
UNION ALL
SELECT 'tb_dev_task_results',
       pg_size_pretty(pg_total_relation_size('tb_dev_task_results')),
       (SELECT count(*) FROM tb_dev_task_results);

SELECT min(created_at) AS oldest_remaining,
       max(created_at) AS newest_remaining
FROM tb_dev_tasks;

\echo ''
\echo '=== Cleanup complete ==='
