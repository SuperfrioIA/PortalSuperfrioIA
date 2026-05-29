#!/bin/sh
set -e

# Garante que o volume montado em /app/data seja gravável pelo user `app`.
# O bind mount preserva o uid:gid do host e pode sobrescrever o chown do build.
chown -R app:app /app/data 2>/dev/null || true

exec gosu app "$@"
