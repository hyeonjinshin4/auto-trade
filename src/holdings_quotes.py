"""보유 종목 현재가 조회·JSON 저장 (대시보드·EOD)."""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path
from typing import Any

from dashboard_config import now_kst_iso, prefer_kis_quotes, quotes_path, journal_path
from journal_fifo import fifo_held_symbols

_NAVER_UA = "Mozilla/5.0"


def fetch_naver_price(symbol: str, *, timeout: float = 8.0) -> int | None:
    code = str(symbol).strip().zfill(6)
    url = f"https://m.stock.naver.com/api/stock/{code}/basic"
    req = urllib.request.Request(url, headers={"User-Agent": _NAVER_UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    raw = data.get("closePrice") or data.get("closePriceKrw") or ""
    if not raw:
        return None
    try:
        return int(str(raw).replace(",", "").strip())
    except ValueError:
        return None


def fetch_kis_price(symbol: str, client: Any) -> int | None:
    try:
        out = client.inquire_price(symbol.strip().zfill(6))
        raw = out.get("stck_prpr") or out.get("stck_clpr") or 0
        px = int(float(str(raw).replace(",", "")))
        return px if px > 0 else None
    except Exception:
        return None


def _kis_client() -> Any | None:
    if not os.getenv("APP_KEY", "").strip():
        return None
    try:
        from kis_client import KISClient

        return KISClient()
    except Exception:
        return None


def fetch_quotes(
    symbols: list[str],
    *,
    prefer_kis: bool = True,
) -> tuple[dict[str, int], str]:
    uniq = sorted({str(s).strip().zfill(6) for s in symbols if str(s).strip()})
    if not uniq:
        return {}, "none"

    client = _kis_client() if prefer_kis else None
    out: dict[str, int] = {}
    kis_hits = 0
    for sym in uniq:
        px: int | None = None
        if client is not None:
            px = fetch_kis_price(sym, client)
            if px:
                kis_hits += 1
        if px is None:
            px = fetch_naver_price(sym)
        if px and px > 0:
            out[sym] = px

    if not out:
        return {}, "none"
    if kis_hits == len(out) == len(uniq):
        return out, "kis"
    if kis_hits == 0:
        return out, "naver"
    return out, "kis+naver"


def build_quotes_payload(
    symbols: list[str],
    *,
    prefer_kis: bool | None = None,
) -> dict[str, Any]:
    use_kis = prefer_kis_quotes() if prefer_kis is None else prefer_kis
    quotes, source = fetch_quotes(symbols, prefer_kis=use_kis)
    return {
        "updated_at": now_kst_iso(),
        "source": source,
        "quotes": {k: {"price": v} for k, v in quotes.items()},
    }


def write_quotes_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def sync_holdings_quotes(
    *,
    journal: Path | None = None,
    out_path: Path | None = None,
    prefer_kis: bool | None = None,
) -> dict[str, Any]:
    """저널 보유 종목 시세 JSON 갱신. quotes_payload 포함 반환."""
    jpath = journal or journal_path()
    qpath = out_path or quotes_path()
    symbols = fifo_held_symbols(jpath)
    payload = (
        build_quotes_payload(symbols, prefer_kis=prefer_kis)
        if symbols
        else {"updated_at": now_kst_iso(), "source": "none", "quotes": {}}
    )
    write_quotes_json(qpath, payload)
    return {
        "quotes_path": qpath,
        "quotes_payload": payload,
        "held_symbols": symbols,
    }


def sync_dashboard_from_env() -> dict[str, Any]:
    return sync_holdings_quotes()


# 하위 호환
sync_dashboard_assets = sync_holdings_quotes
