#!/usr/bin/env bash
set -euo pipefail

mkdir -p /data/configs

exec python /app/app.py
