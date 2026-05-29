"""
장 마감 후 텔레그램 리포트.
  python3 src/eod_report.py --market=kr   # 국내 잔고·수익률·당일 체결
  python3 src/eod_report.py --market=us   # 해외(미국) 체결기준 잔고

cron 예: (한국 시간 기준)
  30 15 * * 1-5 cd /path/to/자동매매 && python3 src/eod_report.py --market=kr
  (EOD_BUILD_DASHBOARD=true 이면 reports/dashboard_eod.html 도 생성)
  또는: python3 scripts/build_eod_dashboard.py
  0 7 * * 2-6 cd /path/to/자동매매 && /usr/bin/python3 src/eod_report.py --market=us
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

from dotenv import load_dotenv

from kis_client import KISClient
from reporting import format_ccld_rows, format_domestic_balance_summary, format_overseas_balance
from telegram_notify import send_telegram


def main() -> int:
    parser = argparse.ArgumentParser(description="장 마감 잔고/체결 텔레그램 리포트")
    parser.add_argument("--market", choices=["kr", "us"], required=True)
    args = parser.parse_args()

    load_dotenv(".env")

    base = (os.getenv("BASE_CAPITAL_KRW") or "").strip()
    today = datetime.now().strftime("%Y%m%d")

    try:
        client = KISClient()
    except Exception as exc:
        print(f"FAILED: auth init ({exc})")
        return 1

    try:
        if args.market == "kr":
            bal = client.inquire_balance()
            fills = client.inquire_daily_ccld(today, today, ccld_dvsn="01")
            msg = f"[한국 장 마감 리포트] {today}\n\n"
            msg += format_domestic_balance_summary(bal, base_capital_krw=base)
            msg += "\n\n"
            msg += format_ccld_rows(fills, title="[금일 국내 체결]", max_rows=40)
        else:
            ob = client.inquire_overseas_present_balance()
            msg = f"[미국 장 마감 리포트] {today}\n\n"
            msg += format_overseas_balance(ob)
        send_telegram(msg)
        if args.market == "kr" and os.getenv("EOD_BUILD_DASHBOARD", "true").strip().lower() in {
            "1",
            "true",
            "yes",
        }:
            try:
                from eod_artifacts import build_eod_artifacts

                paths = build_eod_artifacts()
                print(f"OK: dashboard snapshot {paths['html']}")
            except Exception as dash_exc:
                print(f"WARN: dashboard snapshot skipped ({dash_exc})")
    except Exception as exc:
        print(f"FAILED: ({exc})")
        try:
            send_telegram(f"[eod_report 오류] market={args.market}\n{exc!s}")
        except Exception:
            pass
        return 1

    print("OK: telegram sent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
