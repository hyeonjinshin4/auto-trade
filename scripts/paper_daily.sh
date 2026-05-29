#!/usr/bin/env bash
# 장중 1회 등 크론에서 호출: .env 의 DRY_RUN / TELEGRAM_CYCLE_REPORT / TRADING_SIZING_NAV_KRW 를 사용합니다.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
exec python3 src/auto_trade.py
