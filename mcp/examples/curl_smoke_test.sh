#!/usr/bin/env bash
# Minimal smoke test for LEO4 REST API endpoints.
# Usage: LEO4_API_KEY="ApiKey YOUR_KEY" DEVICE_ID=4619 bash curl_smoke_test.sh

set -euo pipefail

BASE_URL="${LEO4_API_URL:-https://dev.leo4.ru/api/v1}"
API_KEY="${LEO4_API_KEY:-ApiKey CHANGE_ME}"
DEVICE_ID="${DEVICE_ID:-4619}"

echo "=== LEO4 REST API Smoke Test ==="
echo "Base URL : $BASE_URL"
echo "Device ID: $DEVICE_ID"
echo ""

# 1. Create hello task
echo "1. POST /device-tasks/ (hello, method_code=20)"
TASK=$(curl -s -X POST "$BASE_URL/device-tasks/" \
  -H "x-api-key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"device_id\": $DEVICE_ID, \"method_code\": 20, \"ttl\": 5, \"priority\": 1, \"ext_task_id\": \"smoke-$(date +%s)\", \"payload\": {\"dt\": [{\"mt\": 0}]}}")
echo "$TASK"
TASK_ID=$(echo "$TASK" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# 2. Get task status
echo ""
echo "2. GET /device-tasks/$TASK_ID"
curl -s "$BASE_URL/device-tasks/$TASK_ID" \
  -H "x-api-key: $API_KEY" | python3 -m json.tool

# 3. Get recent events
echo ""
echo "3. GET /device-events/fields/ (CellOpenEvent polling)"
curl -s "$BASE_URL/device-events/fields/?device_id=$DEVICE_ID&event_type_code=13&tag=304&interval_m=5&limit=5" \
  -H "x-api-key: $API_KEY" | python3 -m json.tool

# 4. List webhooks
echo ""
echo "4. GET /webhooks/"
curl -s "$BASE_URL/webhooks/" \
  -H "x-api-key: $API_KEY" | python3 -m json.tool

echo ""
echo "=== Smoke test complete ==="
