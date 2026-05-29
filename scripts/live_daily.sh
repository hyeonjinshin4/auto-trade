#!/usr/bin/env bash
# 실매매 크론용: .env 에 DRY_RUN=false, CONFIRM_LIVE=I_ACCEPT_ORDER_RISK, 텔레그램 설정 후 사용.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
exec python3 src/auto_trade.py
