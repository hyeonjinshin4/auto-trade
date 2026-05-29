"""
시장 국면용 MarketRegimeSnapshot 채우기 (FinanceDataReader).
실패 시 None 위주 스냅샷 + meta에 오류 사유 (주문 로직은 계속 가능).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any

from trading_rules.models import MarketRegimeSnapshot, RegimeThresholds

_CODE_TO_KRX_NAME: dict[str, str] | None = None


def _load_krx_code_to_name() -> dict[str, str]:
    """프로세스당 1회 FDR KRX 상장명 캐시 (텔레그램·컨텍스트용)."""
    global _CODE_TO_KRX_NAME
    if _CODE_TO_KRX_NAME is not None:
        return _CODE_TO_KRX_NAME
    _CODE_TO_KRX_NAME = {}
    if (os.getenv("SKIP_FDR_SNAPSHOT") or "").strip().lower() in {"1", "true", "yes", "y"}:
        return _CODE_TO_KRX_NAME
    try:
        import FinanceDataReader as fdr  # type: ignore[import-untyped]

        df = fdr.StockListing("KRX")
        if df is None or len(df) == 0:
            return _CODE_TO_KRX_NAME
        code_col = "Code" if "Code" in df.columns else None
        name_col = "Name" if "Name" in df.columns else None
        if not code_col or not name_col:
            return _CODE_TO_KRX_NAME
        for _, row in df.iterrows():
            c = str(row.get(code_col, "")).strip()
            n = str(row.get(name_col, "")).strip()
            if c:
                _CODE_TO_KRX_NAME[c] = n
    except Exception:
        pass
    return _CODE_TO_KRX_NAME


def _parse_float(x: Any) -> float:
    try:
        return float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def krx_display_name(symbol: str) -> str:
    """종목코드 → 한글명 (없으면 빈 문자열)."""
    sym = str(symbol).strip()
    if not sym:
        return ""
    return _load_krx_code_to_name().get(sym, "")


def fill_market_regime_snapshot_fdr(
    thresholds: RegimeThresholds,
    *,
    lookback_days: int = 150,
) -> tuple[MarketRegimeSnapshot, dict[str, Any]]:
    """
    KOSPI / NASDAQ / VIX 일봉으로 스냅샷 추정.
    반환: (snapshot, meta) meta에는 vix_close, kospi_close, warnings 등.
    """
    meta: dict[str, Any] = {"source": "fdr", "warnings": []}
    if (os.getenv("SKIP_FDR_SNAPSHOT") or "").strip().lower() in {"1", "true", "yes", "y"}:
        meta["warnings"].append("SKIP_FDR_SNAPSHOT set — snapshot not filled")
        return MarketRegimeSnapshot(), meta

    try:
        import FinanceDataReader as fdr  # type: ignore[import-untyped]
    except ImportError:
        meta["warnings"].append("FinanceDataReader not installed")
        return MarketRegimeSnapshot(), meta

    end = datetime.now()
    start = end - timedelta(days=lookback_days)

    snap = MarketRegimeSnapshot()
    vix_close: float | None = None

    try:
        kospi = fdr.DataReader("KS11", start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        if kospi is None or len(kospi) < thresholds.kospi_ma_long + 2:
            meta["warnings"].append("KOSPI data insufficient")
        else:
            c = kospi["Close"].astype(float)
            ma20 = c.rolling(window=thresholds.kospi_ma_short).mean()
            ma60 = c.rolling(window=thresholds.kospi_ma_long).mean()
            last = kospi.iloc[-1]
            cl = _parse_float(last["Close"])
            m20 = _parse_float(ma20.iloc[-1])
            m60 = _parse_float(ma60.iloc[-1])
            meta["kospi_close"] = cl
            meta["kospi_ma20"] = m20
            meta["kospi_ma60"] = m60
            snap.kospi_above_ma20 = cl > m20 if m20 > 0 else None
            snap.kospi_above_ma60 = cl > m60 if m60 > 0 else None
    except Exception as exc:
        meta["warnings"].append(f"KOSPI: {exc!s}")

    try:
        ixic = fdr.DataReader("IXIC", start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        if ixic is not None and len(ixic) >= thresholds.kospi_ma_long:
            c = ixic["Close"].astype(float)
            ma60 = c.rolling(window=thresholds.kospi_ma_long).mean()
            cl = _parse_float(c.iloc[-1])
            m60 = _parse_float(ma60.iloc[-1])
            meta["ixic_close"] = cl
            meta["ixic_ma60"] = m60
            snap.nasdaq_uptrend = cl > m60 if m60 > 0 else None
            if len(c) >= 2:
                prev = _parse_float(c.iloc[-2])
                if prev > 0 and (cl / prev - 1.0) <= -0.05:
                    snap.us_market_crash = True
    except Exception as exc:
        meta["warnings"].append(f"IXIC: {exc!s}")

    try:
        vix = fdr.DataReader("VIX", start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        if vix is not None and len(vix) >= 2:
            vix_close = _parse_float(vix["Close"].iloc[-1])
            prev = _parse_float(vix["Close"].iloc[-2])
            meta["vix_close"] = vix_close
            if prev > 0 and vix_close >= prev * 1.12:
                snap.vix_spike = True
            elif vix_close >= thresholds.vix_risk_off:
                snap.vix_spike = True
            else:
                snap.vix_spike = False
    except Exception as exc:
        meta["warnings"].append(f"VIX: {exc!s}")

    return snap, meta


def _equity_context_from_df(df: Any, out: dict[str, Any]) -> dict[str, Any]:
    """일봉 DataFrame → fetch_equity_context_fdr 필드 채우기."""
    import pandas as pd

    if df is None or len(df) < 3:
        out["warnings"].append("equity data insufficient")
        return out
    c = df["Close"].astype(float)
    cl = _parse_float(c.iloc[-1])
    prev = _parse_float(c.iloc[-2])
    out["last_close"] = cl
    if prev > 0:
        out["daily_change_pct"] = (cl / prev) - 1.0

    streak = 0
    for i in range(len(c) - 1, 0, -1):
        if _parse_float(c.iloc[i]) > _parse_float(c.iloc[i - 1]):
            streak += 1
        else:
            break
    out["consecutive_up_days"] = streak

    if len(df) >= 20 and all(x in df.columns for x in ("High", "Low", "Close")):
        h = df["High"].astype(float)
        l = df["Low"].astype(float)
        prev_c = c.shift(1)
        hl = h - l
        hcp = (h - prev_c).abs()
        lcp = (l - prev_c).abs()
        tr = pd.concat([hl, hcp, lcp], axis=1).max(axis=1)
        atr = tr.ewm(span=14, adjust=False).mean()
        atr_now = _parse_float(atr.iloc[-1])
        base = atr.iloc[-22:-2] if len(atr) >= 22 else atr.iloc[:-1]
        atr_bl = float(base.mean()) if len(base) > 0 else atr_now
        out["atr_14"] = atr_now
        out["atr_baseline"] = atr_bl
        if atr_bl > 0:
            out["atr_ratio"] = atr_now / atr_bl
    return out


def fetch_equity_context_fdr(symbol: str, *, lookback_days: int = 40) -> dict[str, Any]:
    """
    종목 일봉 기준 전일 대비 등락률·연속 상승일 수 (FDR).
    """
    out: dict[str, Any] = {
        "daily_change_pct": None,
        "consecutive_up_days": 0,
        "last_close": None,
        "atr_14": None,
        "atr_baseline": None,
        "atr_ratio": None,
        "name_kr": krx_display_name(symbol),
        "warnings": [],
    }
    if (os.getenv("SKIP_FDR_SNAPSHOT") or "").strip().lower() in {"1", "true", "yes", "y"}:
        out["warnings"].append("SKIP_FDR_SNAPSHOT")
        return out

    try:
        from fdr_ohlcv_cache import get_ohlcv

        # TA와 동일 120일 캐시 — 매수 스캔 시 종목당 FDR 1회
        lb = max(int(lookback_days), 120)
        df = get_ohlcv(symbol, lookback_days=lb)
        if df is None:
            out["warnings"].append("equity data insufficient")
            return out
        return _equity_context_from_df(df, out)
    except Exception as exc:
        out["warnings"].append(f"equity: {exc!s}")
    return out
