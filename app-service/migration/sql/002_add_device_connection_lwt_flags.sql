-- Add app_connect and svc_connect columns to tb_device_connections
ALTER TABLE tb_device_connections
ADD COLUMN IF NOT EXISTS app_connect BOOLEAN DEFAULT NULL,
ADD COLUMN IF NOT EXISTS svc_connect BOOLEAN DEFAULT NULL;

-- Index for filtering devices with known connect state
CREATE INDEX IF NOT EXISTS ix_tb_device_connections_lwt_flags
ON tb_device_connections (app_connect, svc_connect);
