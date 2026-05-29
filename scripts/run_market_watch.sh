#!/usr/bin/env bash
# EC2: Python 3.10+ 로 market_watch 실행 (3.9 의 str|None 오류 방지)
set -euo pipefail
export PYTHONUNBUFFERED=1
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${PYTHON_BIN:-python3.11}"
if ! command -v "$PY" >/dev/null 2>&1; then
  PY=python3
fi
"$PY" -c "import sys; v=sys.version_info; assert v>=(3,10), f'Python 3.10+ 필요, 현재 {v.major}.{v.minor}'"
exec "$PY" src/market_watch.py "$@"
