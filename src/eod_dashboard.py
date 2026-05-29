"""장 마감 후 대시보드 HTML 스냅샷 (file:// 로 열기)."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from dashboard_config import (
    ROOT,
    base_nav_krw,
    eod_html_path,
    journal_path,
    now_kst_label,
    prefer_kis_quotes,
)
from journal_fifo import fifo_held_symbols
from holdings_quotes import sync_holdings_quotes

EOD_MARKER = "const EOD_EMBED = null;"
_log = logging.getLogger(__name__)


def _load_names_subset(codes: list[str]) -> dict[str, str]:
    path = ROOT / "config" / "stock_names.json"
    if not path.is_file():
        return {}
    try:
        full = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {
        str(c).strip().zfill(6): full[str(c).strip().zfill(6)]
        for c in codes
        if str(c).strip().zfill(6) in full
    }


def build_eod_dashboard_html(
    *,
    template_path: Path | None = None,
    output_path: Path | None = None,
    prefer_kis: bool | None = None,
) -> Path:
    template = template_path or ROOT / "dashboard.html"
    out = output_path or eod_html_path()
    journal = journal_path()
    if not journal.is_file():
        raise FileNotFoundError(f"저널 없음: {journal}")

    use_kis = prefer_kis_quotes() if prefer_kis is None else prefer_kis
    meta = sync_holdings_quotes(journal=journal, prefer_kis=use_kis)
    quotes_payload: dict[str, Any] = meta["quotes_payload"]
    journal_csv = journal.read_text(encoding="utf-8")
    held = fifo_held_symbols(journal)

    embed = {
        "journalCsv": journal_csv,
        "quotes": quotes_payload,
        "names": _load_names_subset(held),
        "baseNav": base_nav_krw(),
        "generatedAt": now_kst_label(),
    }

    html = template.read_text(encoding="utf-8")
    if EOD_MARKER not in html:
        raise ValueError(f"dashboard.html 에 '{EOD_MARKER}' 가 없습니다.")

    html = html.replace(EOD_MARKER, "const EOD_EMBED = " + json.dumps(embed, ensure_ascii=False) + ";", 1)
    title_m = re.search(r"<title>([^<]*)</title>", html)
    if title_m:
        html = html.replace(title_m.group(0), f"<title>수익 대시보드 · {embed['generatedAt']}</title>", 1)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")

    try:
        from journal_export import build_trade_export_csv

        csv_out = build_trade_export_csv(journal=journal)
        _log.info("trade export csv: %s", csv_out)
    except Exception as exc:
        _log.warning("trade export csv skipped: %s", exc)

    return out
