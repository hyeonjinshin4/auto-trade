"""장 마감 후 reports/dashboard_eod.html · trade_export CSV 자동 생성 (KST, AWS UTC 대응)."""
from __future__ import annotations

import json
import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from dashboard_config import KST, env_bool, journal_path, now_kst, now_kst_label, resolve_data_path

_log = logging.getLogger(__name__)


def _parse_hhmm(raw: str, default: tuple[int, int]) -> tuple[int, int]:
    s = (raw or "").strip()
    if not s:
        return default
    parts = s.replace(".", ":").split(":")
    try:
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 0
    except (ValueError, IndexError):
        return default
    return max(0, min(23, h)), max(0, min(59, m))


def eod_state_path() -> Path:
    return resolve_data_path("EOD_AUTO_BUILD_STATE_PATH", "logs/eod_build_state.json")


def eod_auto_build_enabled() -> bool:
    return env_bool("EOD_AUTO_BUILD", "true") and env_bool("EOD_BUILD_DASHBOARD", "true")


def is_kr_equity_session_kst(now: datetime | None = None) -> bool:
    """KST 평일 09:00~15:30 (서버 TZ와 무관)."""
    d = (now or now_kst()).astimezone(KST)
    if d.weekday() >= 5:
        return False
    minutes = d.hour * 60 + d.minute
    return (9 * 60) <= minutes <= (15 * 60 + 30)


def is_eod_build_window_kst(now: datetime | None = None) -> bool:
    """KST 평일, EOD_AUTO_BUILD_AFTER_KST 이후~자정."""
    d = (now or now_kst()).astimezone(KST)
    if d.weekday() >= 5:
        return False
    h, m = _parse_hhmm(os.getenv("EOD_AUTO_BUILD_AFTER_KST", "15:35"), (15, 35))
    return d.hour * 60 + d.minute >= h * 60 + m


def _journal_mtime() -> float:
    jp = journal_path()
    return jp.stat().st_mtime if jp.is_file() else 0.0


def _load_state() -> dict[str, Any]:
    p = eod_state_path()
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: dict[str, Any]) -> None:
    p = eod_state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def needs_eod_build(now: datetime | None = None) -> bool:
    if not eod_auto_build_enabled():
        return False
    if not journal_path().is_file():
        return False
    d = (now or now_kst()).astimezone(KST)
    if not is_eod_build_window_kst(d):
        return False

    date_key = d.strftime("%Y-%m-%d")
    jm = _journal_mtime()
    state = _load_state()
    if state.get("last_built_date") != date_key:
        return True
    return jm > float(state.get("journal_mtime") or 0)


def _maybe_upload_s3(paths: list[Path]) -> None:
    bucket = (os.getenv("EOD_S3_BUCKET") or "").strip()
    if not bucket:
        return
    prefix = (os.getenv("EOD_S3_PREFIX") or "autotrade/reports/").strip()
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    for path in paths:
        dest = f"s3://{bucket}/{prefix}{path.name}"
        try:
            subprocess.run(
                ["aws", "s3", "cp", str(path), dest],
                check=True,
                capture_output=True,
                text=True,
            )
            print(f"EOD S3 upload OK: {dest}")
        except FileNotFoundError:
            print("EOD S3 skip: aws CLI 없음")
            return
        except subprocess.CalledProcessError as exc:
            print(f"EOD S3 upload FAILED ({path.name}): {exc.stderr or exc}")


def _maybe_telegram(paths: dict[str, Path]) -> None:
    if not env_bool("EOD_TELEGRAM_NOTIFY", "false"):
        return
    try:
        from telegram_notify import send_telegram

        msg = (
            f"[장마감 대시보드] {now_kst_label()}\n"
            f"HTML: {paths['html']}\n"
            f"CSV: {paths['csv']}"
        )
        bucket = (os.getenv("EOD_S3_BUCKET") or "").strip()
        if bucket:
            prefix = (os.getenv("EOD_S3_PREFIX") or "autotrade/reports/").strip().rstrip("/")
            msg += f"\nS3: s3://{bucket}/{prefix}/"
        send_telegram(msg)
    except Exception as exc:
        _log.warning("EOD telegram notify failed: %s", exc)


def build_eod_artifacts() -> dict[str, Path]:
    from eod_dashboard import build_eod_dashboard_html
    from journal_export import build_trade_export_csv, trade_export_csv_path

    html = build_eod_dashboard_html()
    csv = trade_export_csv_path()
    if not csv.is_file():
        csv = build_trade_export_csv(journal=journal_path())

    now = now_kst()
    _save_state(
        {
            "last_built_date": now.strftime("%Y-%m-%d"),
            "last_built_at": now.isoformat(),
            "journal_mtime": _journal_mtime(),
            "html": str(html),
            "csv": str(csv),
        }
    )
    paths = {"html": html, "csv": csv}
    _maybe_upload_s3([html, csv])
    _maybe_telegram(paths)
    return paths


def maybe_build_eod_artifacts(*, force: bool = False) -> bool:
    """조건 충족 시 HTML+CSV 생성. 생성했으면 True."""
    if not force and not needs_eod_build():
        return False
    try:
        paths = build_eod_artifacts()
        print(f"EOD artifacts OK: {paths['html']} | {paths['csv']}")
        return True
    except Exception as exc:
        print(f"EOD artifacts FAILED: {exc}")
        _log.warning("eod artifacts build failed", exc_info=True)
        return False
