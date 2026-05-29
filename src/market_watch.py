"""
장중 일정 간격으로 trade_runner 한 사이클(매도→매수) 반복.

  프로젝트 루트에서 (기본 60초 = 1분):
    TRADING_WATCH=true python3 src/market_watch.py

장중·장마감(EOD HTML) 판정은 **KST(서울)** 기준입니다. AWS EC2가 UTC여도 동작합니다.
공휴일·임시 휴장은 API로 판별하지 않습니다.
장 마감 후(기본 15:35 KST~) reports/dashboard_eod.html · trade_export CSV 자동 생성(EOD_AUTO_BUILD).

장외에도 스캔·드라이런만 돌리려면 .env 에:
  TRADING_WATCH_RUN_OUTSIDE_SESSION=true
(실주문은 여전히 DRY_RUN=false 일 때만 주의.)
"""
from __future__ import annotations

import os
import signal
import sys
import time
from pathlib import Path

_SRC = Path(__file__).resolve().parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from dotenv import load_dotenv

from dashboard_config import now_kst
from eod_artifacts import is_kr_equity_session_kst, maybe_build_eod_artifacts
from secure_env import validate_kis_credentials
from trade_runner import run_trading_cycle, to_bool


def _load_env() -> None:
    root = Path(__file__).resolve().parent.parent
    load_dotenv(root / ".env")


def main() -> int:
    _load_env()
    if os.getenv("SKIP_KIS_ENV_VALIDATION", "").strip().lower() not in {"1", "true", "yes"}:
        min_k = int(os.getenv("KIS_MIN_KEY_LEN", "8"))
        min_s = int(os.getenv("KIS_MIN_SECRET_LEN", "8"))
        try:
            validate_kis_credentials(min_key_len=min_k, min_secret_len=min_s)
        except Exception as exc:
            print(f"FAILED: env validation ({exc})")
            return 1

    if not to_bool(os.getenv("TRADING_WATCH", "false")):
        print("TRADING_WATCH 가 true 가 아니면 실행하지 않습니다.")
        print("  .env 에 TRADING_WATCH=true 추가 후:")
        print("  python3 src/market_watch.py")
        print("또는 한 줄로:")
        print("  TRADING_WATCH=true python3 src/market_watch.py")
        return 0

    interval = max(15, int(os.getenv("TRADING_WATCH_INTERVAL_SEC", "60")))
    dry = to_bool(os.getenv("DRY_RUN", "true"))
    run_outside = to_bool(os.getenv("TRADING_WATCH_RUN_OUTSIDE_SESSION", "false"))
    if not dry:
        print("WARN: DRY_RUN=false — 장중 반복 시 실주문이 반복 전송될 수 있습니다.")

    stop = {"flag": False}

    def _stop(*_: object) -> None:
        stop["flag"] = True

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    print(
        f"market_watch start interval={interval}s dry_run={dry} "
        f"run_outside_session={run_outside} (장중·EOD 판정=KST)"
    )
    print(
        "스킴: (1) 후보 스캔 → (2) 매도·매수 조건 판단·주문 → "
        "(3) 실매수 시 텔레그램 보고(TELEGRAM_POST_BUY_REPORT)"
    )
    print("종료: Ctrl+C")
    while not stop["flag"]:
        now = now_kst()
        in_session = is_kr_equity_session_kst(now)
        if in_session or run_outside:
            if not in_session and run_outside:
                print(f"cycle (장외 강행) {now.strftime('%Y-%m-%d %H:%M KST')}")
            try:
                run_trading_cycle(dry_run=dry)
            except Exception as exc:
                print(f"cycle error: {exc!s}")
        else:
            print(f"skip (장외) {now.strftime('%Y-%m-%d %H:%M KST')}")
        try:
            maybe_build_eod_artifacts()
        except Exception as exc:
            print(f"eod build check error: {exc!s}")
        for _ in range(interval):
            if stop["flag"]:
                break
            time.sleep(1)
    print("stopped")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("stopped")
        sys.exit(0)
