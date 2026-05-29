#!/usr/bin/env bash
# 크론 백업용: KST 장마감 후 HTML·CSV (market_watch 가 죽었을 때)
# 예) crontab -e  →  35 15 * * 1-5 TZ=Asia/Seoul /path/to/자동매매/scripts/cron_eod_kr.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export TZ=Asia/Seoul
exec python3 scripts/build_eod_dashboard.py
