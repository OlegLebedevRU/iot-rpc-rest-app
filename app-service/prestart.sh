#!/usr/bin/env bash

set -e

echo "Alembic upgrade apply migrations.."
alembic upgrade head
echo "Migrations applied!"

exec "$@"