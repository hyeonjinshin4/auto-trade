"""대시보드 경로·환경 설정."""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent.parent


def now_kst() -> datetime:
    return datetime.now(KST)


def now_kst_label() -> str:
    return now_kst().strftime("%Y-%m-%d %H:%M KST")


def now_kst_iso() -> str:
    return now_kst().strftime("%Y-%m-%dT%H:%M:%S%z")


def env_bool(key: str, default: str = "false") -> bool:
    return os.getenv(key, default).strip().lower() in {"1", "true", "yes", "y"}


def prefer_kis_quotes() -> bool:
    return env_bool("DASHBOARD_QUOTES_KIS", "true")


def resolve_data_path(env_key: str, default: str) -> Path:
    raw = (os.getenv(env_key) or default).strip()
    p = Path(raw)
    return p if p.is_absolute() else ROOT / p


def journal_path() -> Path:
    return resolve_data_path("JOURNAL_PATH", "logs/trade_journal.csv")


def quotes_path() -> Path:
    return resolve_data_path("HOLDINGS_QUOTES_PATH", "logs/holdings_quotes.json")


def eod_html_path() -> Path:
    raw = (os.getenv("EOD_DASHBOARD_PATH") or "reports/dashboard_eod.html").strip()
    p = Path(raw)
    return p if p.is_absolute() else ROOT / p


def base_nav_krw() -> int:
    raw = (os.getenv("BASE_CAPITAL_KRW") or os.getenv("DASHBOARD_BASE_NAV") or "1000000").strip()
    try:
        return max(1, int(float(raw.replace(",", ""))))
    except ValueError:
        return 1_000_000
