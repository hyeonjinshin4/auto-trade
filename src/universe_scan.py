"""
KRX 후보 자동 구성 (FinanceDataReader StockListing).
- 시총 상위 풀에서 상위 N종(기본: Marcap 순, `AUTO_SCAN_MAX_SYMBOLS`·`AUTO_SCAN_POOL_TOP`). RANDOM_SAMPLE=true 이면 무작위 샘플.
- 시총 하한(십억): TRADING_MIN_MCAP_BN 우선, 미설정 시 AUTO_SCAN_MIN_MCAP_BN — 룰북과 동일 규칙 권장.
"""
from __future__ import annotations

import os
import random
import time
from pathlib import Path
from typing import Any, Callable

from safe_logging import get_safe_logger

_log = get_safe_logger(__name__)

_listing_cache: dict[str, Any] = {"ts": 0.0, "codes": []}


def to_bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _parse_float(x: Any) -> float:
    try:
        return float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _read_symbol_file(path: str) -> list[str]:
    p = Path(path).expanduser()
    if not p.is_file():
        return []
    out: list[str] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        tok = line.split(",")[0].strip()
        if len(tok) == 6 and tok.isdigit():
            out.append(tok)
    return out


def _fetch_krx_listing_fresh() -> Any:
    import FinanceDataReader as fdr  # type: ignore[import-untyped]

    return fdr.StockListing("KRX")


def _build_codes_from_df(df: Any) -> list[str]:
    """시총·가격·이름 필터 후 Code 6자리 리스트."""
    if df is None or len(df) == 0:
        return []
    d = df.copy()
    if "Code" not in d.columns:
        return []
    d["Code"] = d["Code"].astype(str).str.zfill(6)
    d = d[d["Code"].str.match(r"^\d{6}$", na=False)]

    if "Name" in d.columns:
        bad = d["Name"].astype(str).str.contains(
            r"스팩|리츠|ETF|ETN|우\s*$|1우|2우|3우",
            case=False,
            na=False,
            regex=True,
        )
        d = d[~bad]

    max_px = (os.getenv("AUTO_SCAN_MAX_PRICE_KRW") or "").strip().replace(",", "")
    if max_px and "Close" in d.columns:
        try:
            cap = float(max_px)
            if cap > 0:
                d = d[d["Close"].apply(lambda x: _parse_float(x) <= cap)]
        except Exception:
            pass

    # 시총 하한(십억): TRADING_MIN_MCAP_BN 우선, 없으면 AUTO_SCAN_MIN_MCAP_BN(구·별칭)
    min_bn = (os.getenv("TRADING_MIN_MCAP_BN") or os.getenv("AUTO_SCAN_MIN_MCAP_BN") or "").strip()
    if min_bn and "Marcap" in d.columns:
        try:
            floor = float(min_bn) * 1_000_000_000.0
            d = d[d["Marcap"].apply(lambda x: _parse_float(x) >= floor)]
        except Exception:
            pass

    mkts = (os.getenv("AUTO_SCAN_MARKET_FILTER") or "").strip().upper()
    if mkts and "MarketId" in d.columns:
        allow = {x.strip() for x in mkts.split(",") if x.strip()}
        if allow:
            d = d[d["MarketId"].astype(str).str.upper().isin(allow)]

    if "Marcap" not in d.columns:
        return d["Code"].head(80).tolist()

    pool_n = max(int(os.getenv("AUTO_SCAN_POOL_TOP", "600")), 50)
    d = d.sort_values("Marcap", ascending=False).head(pool_n)

    # 후보 종목 수 상한(환경으로 조절). 코드 상한은 과도한 API/FDR 부하 방지.
    max_sym = max(5, min(int(os.getenv("AUTO_SCAN_MAX_SYMBOLS", "80")), 300))
    if len(d) <= max_sym:
        return d["Code"].tolist()
    if to_bool(os.getenv("AUTO_SCAN_RANDOM_SAMPLE", "false")):
        return d.sample(n=max_sym, random_state=random.randint(0, 2_147_000_000))["Code"].tolist()
    return d.head(max_sym)["Code"].tolist()


def load_fdr_krx_candidates() -> list[str]:
    if (os.getenv("SKIP_FDR_SNAPSHOT") or "").strip().lower() in {"1", "true", "yes", "y"}:
        _log.warning("SKIP_FDR_SNAPSHOT — 유니버스 스캔 생략")
        return []

    cache_sec = max(60, int(os.getenv("UNIVERSE_LISTING_CACHE_SEC", "3600")))
    now = time.time()
    if _listing_cache["codes"] and (now - float(_listing_cache["ts"])) < cache_sec:
        return list(_listing_cache["codes"])

    try:
        df = _fetch_krx_listing_fresh()
        codes = _build_codes_from_df(df)
        _listing_cache["ts"] = now
        _listing_cache["codes"] = codes
        _log.warning("FDR KRX listing loaded: %s candidates", len(codes))
        return codes
    except Exception as exc:
        _log.error("FDR KRX listing failed: %s", exc)
        return []


def resolve_candidate_symbols(*, to_bool_fn: Callable[[str], bool] = to_bool) -> list[str]:
    """
    우선순위:
    1) AUTO_TRADE_SYMBOLS 비어 있지 않으면 그대로 (수동 후보)
    2) AUTO_UNIVERSE_FILE 이 있으면 파일
    3) AUTO_SCAN_ENABLED 이면 FDR KRX 자동
    4) TEST_SYMBOL
    """
    raw = (os.getenv("AUTO_TRADE_SYMBOLS") or "").strip()
    if raw:
        parts = [p.strip() for p in raw.replace(";", ",").split(",")]
        return [p for p in parts if p]

    path = (os.getenv("AUTO_UNIVERSE_FILE") or "").strip()
    if path:
        codes = _read_symbol_file(path)
        if codes:
            return codes

    if to_bool_fn(os.getenv("AUTO_SCAN_ENABLED", "false")):
        codes = load_fdr_krx_candidates()
        if codes:
            return codes

    return [(os.getenv("TEST_SYMBOL") or "005930").strip()]


def describe_source() -> str:
    if (os.getenv("AUTO_TRADE_SYMBOLS") or "").strip():
        return "AUTO_TRADE_SYMBOLS"
    if (os.getenv("AUTO_UNIVERSE_FILE") or "").strip():
        return "AUTO_UNIVERSE_FILE"
    if to_bool(os.getenv("AUTO_SCAN_ENABLED", "false")):
        return "FDR_KRX_AUTO_SCAN"
    return "TEST_SYMBOL"
