"""
trade_ops — 매매 보조 통합 (상태·가격·breadth·사이클 로직).
"""
from __future__ import annotations

import json
import math
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from kis_client import KISClient
from reporting import append_trade_journal, format_ccld_rows, order_output_odno
from safe_logging import get_safe_logger
from snapshot_filler import fetch_equity_context_fdr
from trading_rules.engine_config import EngineConfig
from trading_rules.exits import ExitContext, evaluate_exit_signals
from trading_rules.loader import get_engine_config
from trading_rules.models import MarketRegime, Rulebook
from trading_rules.pipeline import EntryDecision
from trading_rules.positioning import shares_from_portfolio_risk
from trading_rules.risk_limits import portfolio_heat_ok
from trading_validator import validate_buy_order
from validated_inputs import OrderIntent

_log = get_safe_logger(__name__)
_KST = timezone(timedelta(hours=9))

OrderType = str  # market | limit | best_limit


# --- from trade_state.py ---

from safe_logging import get_safe_logger

_log = get_safe_logger(__name__)
_KST = timezone(timedelta(hours=9))


def _parse_float(x: Any) -> float:
    try:
        return float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _state_path(env_key: str, default_rel: str) -> Path:
    raw = (os.getenv(env_key) or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path(__file__).resolve().parent.parent / default_rel


def position_state_path() -> Path:
    return _state_path("POSITION_STATE_PATH", "logs/position_state.json")


def blocked_symbols_path() -> Path:
    return _state_path("BLOCKED_SYMBOLS_PATH", "logs/blocked_symbols.json")


def buy_attempt_state_path() -> Path:
    return _state_path("BUY_ATTEMPT_STATE_PATH", "logs/buy_attempt_state.json")


def _read_json_dict(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        _log.warning("state read %s: %s", path, exc)
        return {}


def _write_json_dict(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")


def _normalize_position_row(row: dict[str, Any]) -> dict[str, Any] | None:
    ep = _parse_float(row.get("entry_price") or row.get("entry_px"))
    if ep <= 0:
        return None
    hp = _parse_float(row.get("highest_px") or ep)
    return {
        "entry_px": ep,
        "entry_price": ep,
        "highest_px": max(hp, ep),
        "entry_date": str(row.get("entry_date") or ""),
        "tp1_done": bool(row.get("tp1_done", False)),
        "tp2_done": bool(row.get("tp2_done", False)),
    }


def load_position_state() -> dict[str, dict[str, Any]]:
    """{symbol: {entry_px, entry_price, highest_px, entry_date, tp1_done, tp2_done}}"""
    raw = _read_json_dict(position_state_path())
    out: dict[str, dict[str, Any]] = {}
    for sym, row in raw.items():
        if not isinstance(row, dict):
            continue
        norm = _normalize_position_row(row)
        if norm:
            out[str(sym).strip()] = norm
    return out


def save_position_state(state: dict[str, dict[str, Any]]) -> None:
    _write_json_dict(position_state_path(), state)


def register_position_entry(
    state: dict[str, dict[str, Any]],
    symbol: str,
    entry_px: float,
    *,
    entry_date: str | None = None,
) -> None:
    sym = symbol.strip()
    if not sym or entry_px <= 0:
        return
    today = entry_date or datetime.now(_KST).strftime("%Y%m%d")
    prev = state.get(sym)
    if prev:
        hp = max(_parse_float(prev.get("highest_px")), entry_px)
        state[sym] = {
            "entry_px": entry_px,
            "entry_price": entry_px,
            "highest_px": hp,
            "entry_date": prev.get("entry_date") or today,
            "tp1_done": bool(prev.get("tp1_done", False)),
            "tp2_done": bool(prev.get("tp2_done", False)),
        }
    else:
        state[sym] = {
            "entry_px": entry_px,
            "entry_price": entry_px,
            "highest_px": entry_px,
            "entry_date": today,
            "tp1_done": False,
            "tp2_done": False,
        }


def remove_position(state: dict[str, dict[str, Any]], symbol: str) -> None:
    state.pop(symbol.strip(), None)


def update_highest_px(
    state: dict[str, dict[str, Any]],
    symbol: str,
    current_price: float,
) -> float:
    """현재가로 highest_px 갱신 후 highest_px 반환."""
    sym = symbol.strip()
    if current_price <= 0:
        row = state.get(sym)
        return _parse_float(row.get("highest_px")) if row else 0.0
    row = state.get(sym)
    if not row:
        return current_price
    hp = max(_parse_float(row.get("highest_px")), current_price)
    row["highest_px"] = hp
    return hp


def load_blocked_symbols() -> dict[str, str]:
    """{symbol: block_until_yyyymmdd}"""
    raw = _read_json_dict(blocked_symbols_path())
    return {str(k).strip(): str(v).strip() for k, v in raw.items() if k and v}


def save_blocked_symbols(blocks: dict[str, str]) -> None:
    today = datetime.now(_KST).strftime("%Y%m%d")
    pruned = {s: d for s, d in blocks.items() if d >= today}
    _write_json_dict(blocked_symbols_path(), pruned)


def is_symbol_blocked(symbol: str, blocks: dict[str, str] | None = None) -> bool:
    sym = symbol.strip()
    b = blocks if blocks is not None else load_blocked_symbols()
    until = b.get(sym, "")
    if not until:
        return False
    today = datetime.now(_KST).strftime("%Y%m%d")
    return until >= today


def load_buy_attempt_state() -> dict[str, dict[str, Any]]:
    """{symbol: {last_attempt_at, buy_count_date, buy_count}} — KST 기준."""
    raw = _read_json_dict(buy_attempt_state_path())
    out: dict[str, dict[str, Any]] = {}
    for sym, row in raw.items():
        if isinstance(row, dict):
            out[str(sym).strip()] = dict(row)
    return out


def save_buy_attempt_state(state: dict[str, dict[str, Any]]) -> None:
    _write_json_dict(buy_attempt_state_path(), state)


def _buy_cooldown_minutes() -> int:
    try:
        return max(0, int((os.getenv("TRADING_BUY_COOLDOWN_MINUTES") or "60").strip()))
    except ValueError:
        return 60


def _max_buys_per_symbol_per_day() -> int:
    try:
        return max(1, int((os.getenv("TRADING_MAX_BUYS_PER_SYMBOL_PER_DAY") or "1").strip()))
    except ValueError:
        return 1


def allow_rebuy_after_sell() -> bool:
    return (os.getenv("TRADING_ALLOW_REBUY_AFTER_SELL") or "true").strip().lower() not in {
        "0",
        "false",
        "no",
    }


def clear_buy_attempt(
    symbol: str,
    state: dict[str, dict[str, Any]] | None = None,
) -> None:
    """전량 매도 후 재매수 허용 시 쿨다운·당일 카운트 초기화."""
    sym = symbol.strip()
    if not sym:
        return
    st = state if state is not None else load_buy_attempt_state()
    if sym in st:
        del st[sym]
        save_buy_attempt_state(st)


def record_buy_attempt(
    symbol: str,
    *,
    success: bool,
    state: dict[str, dict[str, Any]] | None = None,
) -> None:
    """주문 시도·성공 기록(같은 종목 매 사이클 재매수 방지)."""
    sym = symbol.strip()
    if not sym:
        return
    st = state if state is not None else load_buy_attempt_state()
    today = datetime.now(_KST).strftime("%Y%m%d")
    now_iso = datetime.now(_KST).isoformat(timespec="seconds")
    row = dict(st.get(sym) or {})
    if row.get("buy_count_date") != today:
        row["buy_count_date"] = today
        row["buy_count"] = 0
    if success:
        row["buy_count"] = int(row.get("buy_count") or 0) + 1
        row["last_success_at"] = now_iso
    row["last_attempt_at"] = now_iso
    st[sym] = row
    save_buy_attempt_state(st)


def allow_held_topup_enabled() -> bool:
    return (os.getenv("TRADING_ALLOW_HELD_TOPUP") or "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "y",
    }


def buy_skip_reason(
    symbol: str,
    *,
    buy_attempts: dict[str, dict[str, Any]] | None = None,
    position_state: dict[str, dict[str, Any]] | None = None,
    allow_topup: bool = False,
) -> str | None:
    """
    매수 스킵 사유. None 이면 매수 후보 가능.
    """
    sym = symbol.strip()
    if not sym:
        return "invalid_symbol"

    skip_pos = (os.getenv("TRADING_SKIP_BUY_IF_POSITION_STATE") or "true").strip().lower() not in {
        "0",
        "false",
        "no",
    }
    if (
        skip_pos
        and not allow_topup
        and position_state is not None
        and sym in position_state
    ):
        return "포지션 상태 보유(중복 매수 방지)"

    attempts = buy_attempts if buy_attempts is not None else load_buy_attempt_state()
    row = attempts.get(sym)
    if not row:
        return None

    if not allow_rebuy_after_sell():
        today = datetime.now(_KST).strftime("%Y%m%d")
        max_day = _max_buys_per_symbol_per_day()
        if row.get("buy_count_date") == today and int(row.get("buy_count") or 0) >= max_day:
            return f"당일 매수 한도({max_day}회/종목)"

    cool_min = _buy_cooldown_minutes()
    if cool_min <= 0:
        return None

    raw_ts = str(row.get("last_success_at") or "").strip()
    if not raw_ts:
        return None
    try:
        ts = datetime.fromisoformat(raw_ts)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=_KST)
    except ValueError:
        return None
    elapsed = datetime.now(_KST) - ts
    if elapsed < timedelta(minutes=cool_min):
        left = cool_min - int(elapsed.total_seconds() // 60)
        return f"매수 쿨다운(약 {max(left, 1)}분 남음, {cool_min}분)"
    return None


def block_symbol_reentry(symbol: str, days: int | None = None) -> None:
    sym = symbol.strip()
    if not sym:
        return
    if days is None:
        try:
            days = int((os.getenv("TRADING_REENTRY_BLOCK_DAYS") or "3").strip())
        except ValueError:
            days = 3
    days = max(1, days)
    until = (datetime.now(_KST).date() + timedelta(days=days)).strftime("%Y%m%d")
    blocks = load_blocked_symbols()
    blocks[sym] = until
    save_blocked_symbols(blocks)
    _log.info("[재진입차단] %s until %s (%d일)", sym, until, days)

# --- from trade_pricing.py ---

def trading_order_type() -> OrderType:
    raw = (os.getenv("TRADING_ORDER_TYPE") or "market").strip().lower()
    if raw in {"market", "limit", "best_limit"}:
        return raw
    _log.warning("TRADING_ORDER_TYPE=%s unknown — market", raw)
    return "market"


def slippage_buffer_frac() -> float:
    raw = (os.getenv("TRADING_ENTRY_SLIPPAGE_BUFFER") or "0").strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 0.0


def get_entry_reference_price(
    symbol: str,
    stock_ctx: dict[str, Any],
    *,
    client: Any | None = None,
) -> tuple[float, str]:
    """
    사이징·지정가용 기준가.
    1) KIS 현재가 (client 있고 USE_KIS_QUOTE_FOR_SIZING≠false)
    2) stock_ctx last_close
    3) 0
    """
    last_close = _parse_float(stock_ctx.get("last_close") or 0.0)
    use_kis = (os.getenv("USE_KIS_QUOTE_FOR_SIZING") or "true").strip().lower() not in {
        "0",
        "false",
        "no",
    }
    if client is not None and use_kis:
        try:
            q = client.inquire_price(symbol)
            px = _parse_float(q.get("stck_prpr") or q.get("stck_clpr"))
            if px > 0:
                buf = slippage_buffer_frac()
                if buf > 0:
                    px *= 1.0 + buf
                return px, "kis_quote"
        except Exception as exc:
            _log.debug("KIS quote %s: %s", symbol, exc)

    if last_close > 0:
        buf = slippage_buffer_frac()
        if buf > 0:
            last_close *= 1.0 + buf
        return last_close, "last_close"
    return 0.0, "none"


def krx_tick_size_krw(price: float) -> int:
    """KRX 현금주식 호가단위(원)."""
    p = max(0, int(price))
    if p < 2000:
        return 1
    if p < 5000:
        return 5
    if p < 10000:
        return 10
    if p < 50000:
        return 50
    if p < 100000:
        return 100
    if p < 500000:
        return 500
    return 1000


def round_krx_limit_price(price: float, *, side: str) -> int:
    """
    지정가를 호가단위에 맞춤.
    매수: 내림(체결·증거금 유리), 매도: 올림.
    """
    tick = krx_tick_size_krw(price)
    p = max(float(tick), float(price))
    if side == "sell":
        return int(math.ceil(p / tick) * tick)
    return int(p // tick) * tick


def resolve_order_price(
    order_type: OrderType,
    *,
    reference_price: float,
    side: str = "buy",
) -> tuple[int, str]:
    """
    (주문단가, ORD_DVSN) — KIS 국내 현금주문.
    market/best_limit: 단가 0
    limit: 기준가를 KRX 호가단위로 보정한 지정가
    """
    if order_type == "limit":
        px = round_krx_limit_price(reference_price, side=side)
        return max(1, px), "00"
    if order_type == "best_limit":
        return 0, "05"
    return 0, "01"

# --- from market_breadth.py ---

_cache: dict[str, Any] = {"ts": 0.0, "result": None}


@dataclass(frozen=True)
class MarketBreadthResult:
    score: float
    advance_ratio: float
    index_both_up: bool
    above_ma20_ratio: float | None
    trade_value_breadth: float | None
    detail: str


def _fetch_krx_listing() -> Any:
    import FinanceDataReader as fdr  # type: ignore[import-untyped]

    return fdr.StockListing("KRX")


def _index_last_return(ticker: str, days: int = 30) -> float | None:
    import FinanceDataReader as fdr  # type: ignore[import-untyped]

    end = datetime.now()
    start = end - timedelta(days=days)
    try:
        df = fdr.DataReader(ticker, start, end)
        if df is None or len(df) < 2:
            return None
        c0 = _parse_float(df["Close"].iloc[-2])
        c1 = _parse_float(df["Close"].iloc[-1])
        if c0 <= 0:
            return None
        return (c1 - c0) / c0
    except Exception:
        return None


def _above_ma20_ratio_sample(codes: list[str], *, max_names: int = 60) -> float | None:
    """유동 상위 샘플에서 20일선 위 비율 (FDR 호출 수 제한)."""
    import FinanceDataReader as fdr  # type: ignore[import-untyped]

    if not codes:
        return None
    sample = codes[:max_names]
    end = datetime.now()
    start = end - timedelta(days=45)
    above = 0
    n = 0
    for code in sample:
        try:
            df = fdr.DataReader(code, start, end)
            if df is None or len(df) < 22:
                continue
            close = df["Close"].astype(float)
            ma20 = close.tail(20).mean()
            last = _parse_float(close.iloc[-1])
            if ma20 > 0 and last > ma20:
                above += 1
            n += 1
        except Exception:
            continue
    if n < 10:
        return None
    return above / n


def compute_kr_market_breadth(*, ma_sample_size: int = 60) -> MarketBreadthResult:
    """
    breadth_score 0~100 (높을수록 시장 내부 강도 양호).
    구성: 상승종목비율, KOSPI·KOSDAQ 동반상승, (가능 시) 20일선 위 비율, 거래대금 breadth.
    """
    parts: list[str] = []
    scores: list[float] = []

    try:
        df = _fetch_krx_listing()
    except Exception as exc:
        _log.warning("breadth listing failed: %s", exc)
        return MarketBreadthResult(
            score=50.0,
            advance_ratio=0.5,
            index_both_up=False,
            above_ma20_ratio=None,
            trade_value_breadth=None,
            detail=f"listing_fail:{exc}",
        )

    if df is None or len(df) == 0 or "Code" not in df.columns:
        return MarketBreadthResult(
            score=50.0,
            advance_ratio=0.5,
            index_both_up=False,
            above_ma20_ratio=None,
            trade_value_breadth=None,
            detail="listing_empty",
        )

    d = df.copy()
    d["Code"] = d["Code"].astype(str).str.zfill(6)
    if "Change" in d.columns:
        chg = d["Change"].apply(_parse_float)
        valid = chg.notna()
        if valid.sum() > 50:
            adv = float((chg[valid] > 0).sum()) / float(valid.sum())
            scores.append(adv * 100.0)
            parts.append(f"상승비율={adv * 100:.1f}%")
        else:
            adv = 0.5
    else:
        adv = 0.5
        parts.append("상승비율=NA")

    k_ret = _index_last_return("KS11")
    q_ret = _index_last_return("KQ11")
    both_up = (k_ret is not None and k_ret > 0) and (q_ret is not None and q_ret > 0)
    scores.append(100.0 if both_up else 20.0)
    parts.append(f"지수동반={'Y' if both_up else 'N'}(KOSPI={k_ret}, KOSDAQ={q_ret})")

    above_ma: float | None = None
    if "Marcap" in d.columns:
        top = d.sort_values("Marcap", ascending=False).head(ma_sample_size)
        codes = top["Code"].tolist()
        above_ma = _above_ma20_ratio_sample(codes, max_names=min(60, ma_sample_size))
        if above_ma is not None:
            scores.append(above_ma * 100.0)
            parts.append(f"20일선위={above_ma * 100:.1f}%")

    tv_breadth: float | None = None
    if "Change" in d.columns and "Volume" in d.columns and "Close" in d.columns:
        sub = d[["Change", "Volume", "Close"]].copy()
        sub["tv"] = sub["Volume"].apply(_parse_float) * sub["Close"].apply(_parse_float)
        sub["chg"] = sub["Change"].apply(_parse_float)
        up_tv = float(sub.loc[sub["chg"] > 0, "tv"].sum())
        dn_tv = float(sub.loc[sub["chg"] < 0, "tv"].sum())
        tot = up_tv + dn_tv
        if tot > 0:
            tv_breadth = up_tv / tot
            scores.append(tv_breadth * 100.0)
            parts.append(f"거래대금상승비={tv_breadth * 100:.1f}%")

    composite = sum(scores) / len(scores) if scores else 50.0
    return MarketBreadthResult(
        score=composite,
        advance_ratio=adv,
        index_both_up=both_up,
        above_ma20_ratio=above_ma,
        trade_value_breadth=tv_breadth,
        detail=" | ".join(parts),
    )


def compute_kr_market_breadth_cached() -> MarketBreadthResult:
    sec = max(300, int(os.getenv("BREADTH_CACHE_SEC", "1800")))
    now = time.time()
    if _cache["result"] is not None and (now - float(_cache["ts"])) < sec:
        return _cache["result"]
    res = compute_kr_market_breadth()
    _cache["ts"] = now
    _cache["result"] = res
    _log.info("[BREADTH] score=%.1f %s", res.score, res.detail)
    return res

# --- from trade_cycle.py ---

def parse_float(x: Any) -> float:
    return _parse_float(x)


def kis_rt_ok(rt: str) -> bool:
    return (rt or "").strip() in {"0", "00"}


def commission_round_trip_kr(ec: EngineConfig) -> float:
    return 2.0 * max(0.0, ec.commission.kr_one_way)


def trail_width_for_pnl(pnl_frac: float, sell: Any) -> float:
    if hasattr(sell, "trailing_width"):
        return sell.trailing_width(pnl_frac)
    if pnl_frac >= sell.trailing_width_stage3_from_gain_pct:
        return sell.trailing_width_stage3_pct
    if pnl_frac >= sell.trailing_width_stage2_from_gain_pct:
        return sell.trailing_width_stage2_pct
    return sell.trailing_width_stage1_pct


def _holding_days_from_row(row: dict[str, Any], position: dict[str, Any] | None) -> int:
    raw = (position or {}).get("entry_date") or row.get("pchs_dt") or row.get("buy_dt") or row.get(
        "pchs_stt_dt"
    )
    if raw is None:
        return 0
    ds = str(raw).strip()
    if len(ds) == 8 and ds.isdigit():
        try:
            d0 = datetime.strptime(ds, "%Y%m%d").date()
            return (datetime.now().date() - d0).days
        except ValueError:
            return 0
    return 0


def _ta_sell_metrics_for_symbol(sym: str, sell: Any) -> tuple[int, float]:
    """(주요 TA 매도 시그널 수, 청산용 점수). 쿨다운 중이면 0."""
    try:
        from signal_scanner.config import load_watchlist
        from signal_scanner.cooldown import in_cooldown
        from signal_scanner.rules import primary_sell_hits
        from signal_scanner.runner import evaluate_symbol_signals
        from signal_scanner.ta_scoring import score_ta_sell_exit
        from signal_scanner.trading import use_ta_signals

        if not use_ta_signals():
            return 0, 0.0
        cd_key = f"trade:{sym.strip()}:sell"
        cfg = load_watchlist()
        if in_cooldown(cd_key, "", float(sell.ta_sell_cooldown_hours)):
            return 0, 0.0
        ev = evaluate_symbol_signals(sym, cfg)
        if ev is None:
            return 0, 0.0
        _, sell_hits, today = ev
        from signal_scanner.rules import trend_allows_sell

        trend_ok = trend_allows_sell(today, cfg)
        detail = score_ta_sell_exit(sell_hits, cfg, trend_ok=trend_ok)
        n_primary = len(primary_sell_hits(sell_hits))
        score = float(detail.raw_points) if detail.score > 0 else 0.0
        return n_primary, score
    except Exception as exc:
        _log.debug("ta_sell metrics %s: %s", sym, exc)
        return 0, 0.0


def evaluate_holding_sell(
    row: dict[str, Any],
    rulebook: Rulebook,
    stock_ctx: dict[str, Any],
    *,
    position: dict[str, Any] | None = None,
    current_price: float | None = None,
) -> "SellDecision":
    from trading_rules.sell_decision import SellDecision, evaluate_sell

    sym = str(row.get("pdno", "")).strip()
    pos = position or {}
    entry_px = parse_float(pos.get("entry_price") or pos.get("entry_px"))
    if entry_px <= 0:
        entry_px = parse_float(
            row.get("pchs_avg_pric") or row.get("pchs_unpr") or row.get("avg_prvs") or 0.0
        )
    highest_px = parse_float(pos.get("highest_px") or entry_px)
    cur = current_price if current_price and current_price > 0 else parse_float(
        stock_ctx.get("last_close") or 0.0
    )
    ma20 = parse_float(stock_ctx.get("ma_slow") or 0.0)
    if ma20 <= 0 and sym:
        try:
            from signal_scanner.config import load_watchlist
            from signal_scanner.runner import evaluate_symbol_signals

            ev = evaluate_symbol_signals(sym, load_watchlist())
            if ev is not None:
                _, _, today = ev
                ma20 = parse_float(today.get("ma_slow") or 0.0)
                if ma20 > 0:
                    stock_ctx["ma_slow"] = ma20
        except Exception:
            pass
    price_vs_ma20 = (cur / ma20) if ma20 > 0 and cur > 0 else 0.0
    ta_count, ta_score = _ta_sell_metrics_for_symbol(sym, rulebook.sell) if sym else (0, 0.0)
    atr_v = parse_float(stock_ctx.get("atr_14") or 0.0) or None

    return evaluate_sell(
        current_price=cur,
        entry_price=entry_px,
        highest_price=highest_px,
        holding_days=_holding_days_from_row(row, pos),
        atr_value=atr_v if atr_v and atr_v > 0 else None,
        price_vs_ma20=price_vs_ma20,
        ta_signal_count=ta_count,
        ta_signal_score=ta_score,
        tp1_done=bool(pos.get("tp1_done", False)),
        tp2_done=bool(pos.get("tp2_done", False)),
        sell=rulebook.sell,
    )


def sell_qty_for_ratio(hold_qty: int, sell_ratio: float) -> int:
    """보유 수량 × 매도 비율 → 주문 수량 (최소 1주, 상한 보유)."""
    if hold_qty <= 0:
        return 0
    if sell_ratio >= 1.0:
        return hold_qty
    q = int(hold_qty * sell_ratio)
    if q < 1:
        q = 1
    return min(q, hold_qty)


def apply_sell_decision_to_position(
    pos_state: dict[str, dict[str, Any]],
    sym: str,
    decision: "SellDecision",
) -> None:
    """분할 익절 후 tp 플래그 갱신. 전량 매도 시 포지션 제거는 호출측."""
    row = pos_state.get(sym.strip())
    if not row:
        return
    if decision.action == "take_profit_1":
        row["tp1_done"] = True
    elif decision.action == "take_profit_2":
        row["tp2_done"] = True


def sell_reasons(
    row: dict[str, Any],
    rulebook: Rulebook,
    ec: EngineConfig,
    stock_ctx: dict[str, Any],
    *,
    atr_stop_mult: float = 1.0,
    position: dict[str, Any] | None = None,
    current_price: float | None = None,
) -> list[str]:
    """하위 호환 — evaluate_holding_sell 결과를 문자열 리스트로."""
    _ = ec, atr_stop_mult
    dec = evaluate_holding_sell(
        row, rulebook, stock_ctx, position=position, current_price=current_price
    )
    if dec.action == "hold":
        return []
    tag = "trailing_stop" if dec.action == "trail_stop" else dec.action
    if dec.action == "ta_sell":
        tag = "technical:TA"
    return [f"{tag}:{dec.reason}"]


def log_holdings_summary(balance: dict[str, Any]) -> float:
    """[보유현황] 한 줄 + 합계평가 반환."""
    o1 = balance.get("output1")
    if not isinstance(o1, list) or not o1:
        print("[보유현황] 보유 없음")
        return 0.0
    parts: list[str] = []
    total = 0.0
    for row in o1:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("pdno", "")).strip()
        q = int(parse_float(row.get("hldg_qty", 0)))
        if q <= 0:
            continue
        pnl_rt = parse_float(row.get("evlu_pfls_rt") or 0.0)
        ev = parse_float(row.get("evlu_amt") or 0.0)
        total += ev
        parts.append(f"{sym} {pnl_rt:+.1f}%")
    if parts:
        line = "[보유현황] " + " | ".join(parts[:8])
        if len(parts) > 8:
            line += f" | 외 {len(parts) - 8}종"
        line += f" | 합계평가 {total:,.0f}원"
        print(line)
        _log.info(line)
    else:
        print("[보유현황] 보유 없음")
    return total


def place_order(
    client: KISClient,
    *,
    side: str,
    symbol: str,
    qty: int,
    reference_price: float,
    order_type: str | None = None,
) -> dict[str, Any]:
    otype = order_type or trading_order_type()
    px, dvsn = resolve_order_price(otype, reference_price=reference_price, side=side)
    if side == "buy":
        return client.place_order_cash_buy(symbol, qty, price=px, order_dvsn=dvsn)
    return client.place_order_cash_sell(symbol, qty, price=px, order_dvsn=dvsn)


@dataclass
class BuyCandidate:
    symbol: str
    score: float
    qty: int
    decision: EntryDecision
    stock_ctx: dict[str, Any]
    entry_px: float
    stop_px: float
    ref_source: str
    is_topup: bool = False


@dataclass(frozen=True)
class HoldingEntryDiagnosis:
    symbol: str
    tier: str
    score: float
    pnl_pct: float
    explanation: str
    blocked: bool = False
    eval_error: str | None = None


def holding_entry_scan_enabled() -> bool:
    return (os.getenv("TRADING_SCAN_HELD_ENTRY") or "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "y",
    }


def _env_to_bool(v: str) -> bool:
    return str(v).strip().lower() in {"1", "true", "yes", "y"}


def evaluate_entry_score(
    sym: str,
    *,
    snap: Any,
    vix_f: float | None,
    risk_off: bool,
    vix_spike: bool,
    adaptive_out: Any,
    use_pipeline: bool,
    regime_enum: MarketRegime,
    client: KISClient | None,
    rs_pct: float | None = None,
) -> tuple[EntryDecision | None, dict[str, Any], str]:
    """
    엔진+TA 통합 진입 점수만 계산 (보유·사이징·검증 없음).
    반환: (decision, stock_ctx, ref_src). 실패 시 (None, ctx, skip_reason).
    """
    from trading_rules.signal_from_context import signal_components_from_context

    stock_ctx: dict[str, Any] = dict(fetch_equity_context_fdr(sym))
    stock_ctx.setdefault("using_leverage", _env_to_bool(os.getenv("USING_LEVERAGE", "false")))
    stock_ctx.setdefault("community_chase", _env_to_bool(os.getenv("COMMUNITY_CHASE_FLAG", "false")))
    stock_ctx.setdefault("recent_avg_down", _env_to_bool(os.getenv("RECENT_AVG_DOWN_FLAG", "false")))
    if rs_pct is not None:
        stock_ctx["rs_composite_pct"] = rs_pct

    entry_px, ref_src = get_entry_reference_price(sym, stock_ctx, client=client)
    if entry_px <= 0:
        return None, stock_ctx, "기준가 없음"

    components = signal_components_from_context(stock_ctx, snap)
    dchg = stock_ctx.get("daily_change_pct")
    high_vol = dchg is not None and abs(float(dchg)) >= 0.06
    ar = stock_ctx.get("atr_ratio")
    if ar is not None and float(ar) >= 1.35:
        high_vol = True

    try:
        from signal_scanner.trading import use_ta_signals
        from signal_scanner.unified import decide_entry_unified

        if use_pipeline or use_ta_signals():
            decision = decide_entry_unified(
                snap,
                components,
                symbol=sym,
                vix_level=vix_f,
                risk_off=risk_off,
                vix_spike=vix_spike,
                is_high_stock_vol=high_vol,
                adaptive=adaptive_out,
                use_engine=use_pipeline,
            )
            return decision, stock_ctx, ref_src
        return (
            EntryDecision(
                tier="full",
                position_fraction=1.0,
                signal_raw=70.0,
                signal_adjusted=70.0,
                regime_score=50.0,
                regime_label=regime_enum.value,
                conflict_reasons=(),
                size_multiplier=1.0,
                explanation="USE_ENTRY_PIPELINE=false, USE_TA_SIGNALS=false",
            ),
            stock_ctx,
            ref_src,
        )
    except Exception as exc:
        _log.warning("entry score failed %s: %s", sym, exc)
        return None, stock_ctx, str(exc)


def scan_held_positions_entry(
    holdings: list[dict[str, Any]],
    *,
    snap: Any,
    vix_f: float | None,
    risk_off: bool,
    vix_spike: bool,
    adaptive_out: Any,
    use_pipeline: bool,
    regime_enum: MarketRegime,
    client: KISClient | None,
    blocked: dict[str, str],
    rs_pct_by_symbol: dict[str, float] | None = None,
    max_open: int,
) -> list[HoldingEntryDiagnosis]:
    """슬롯 만석 시 보유 종목만 매수 조건(엔진+TA) 재평가."""
    if not holdings:
        print("[보유진단] 보유 없음")
        return []

    rs_map = rs_pct_by_symbol or {}
    out: list[HoldingEntryDiagnosis] = []

    for row in holdings:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("pdno", "")).strip()
        if not sym:
            continue
        pnl = _parse_float(row.get("evlu_pfls_rt") or 0.0)
        if is_symbol_blocked(sym, blocked):
            out.append(
                HoldingEntryDiagnosis(
                    symbol=sym,
                    tier="skip",
                    score=0.0,
                    pnl_pct=pnl,
                    explanation="재진입 차단 중",
                    blocked=True,
                )
            )
            continue

        decision, _ctx, ref_or_err = evaluate_entry_score(
            sym,
            snap=snap,
            vix_f=vix_f,
            risk_off=risk_off,
            vix_spike=vix_spike,
            adaptive_out=adaptive_out,
            use_pipeline=use_pipeline,
            regime_enum=regime_enum,
            client=client,
            rs_pct=rs_map.get(sym),
        )
        if decision is None:
            out.append(
                HoldingEntryDiagnosis(
                    symbol=sym,
                    tier="skip",
                    score=0.0,
                    pnl_pct=pnl,
                    explanation=ref_or_err,
                    eval_error=ref_or_err,
                )
            )
            continue

        tier = decision.tier
        score = float(decision.signal_adjusted)
        expl = (decision.explanation or "")[:160]
        out.append(
            HoldingEntryDiagnosis(
                symbol=sym,
                tier=tier,
                score=score,
                pnl_pct=pnl,
                explanation=expl,
            )
        )

    out.sort(key=lambda d: d.score, reverse=True)
    ok = [d for d in out if d.tier == "full" and not d.blocked]
    half = [d for d in out if d.tier == "half" and not d.blocked]
    weak = [d for d in out if d.tier == "skip" and not d.blocked]

    print(
        f"[보유진단] 슬롯 {len(holdings)}/{max_open} 만석 — 보유 {len(out)}종 매수조건 재평가 "
        f"| 비중확대가능(full) {len(ok)}종 | half만 {len(half)}종 | skip {len(weak)}종"
    )
    _log.info(
        "[보유진단] held=%d ok=%d weak=%d",
        len(out),
        len(ok),
        len(weak),
    )
    for d in out:
        tag = "◎" if d.tier == "full" else ("○" if d.tier == "half" else "·")
        if d.blocked:
            tag = "×"
        expl_short = d.explanation.replace("\n", " ")[:100]
        print(
            f"[보유진단] {tag} {d.symbol} 수익{d.pnl_pct:+.1f}% "
            f"tier={d.tier} 점수={d.score:.1f} | {expl_short}"
        )
    if ok:
        tops = ", ".join(f"{d.symbol}({d.score:.0f})" for d in ok[:6])
        print(f"[보유진단] 비중확대 가능(full): {tops}")
    elif half:
        print(f"[보유진단] half만 해당(확대 안 함): {', '.join(d.symbol for d in half[:6])}")
    else:
        print("[보유진단] 비중확대 가능(full) 종목 없음")
    print(
        f"SKIP_BUY: 슬롯 만석({len(holdings)}/{max_open}) — "
        "신규 후보 스캔 생략 · 보유진단만 수행"
    )
    return out


def max_buys_per_cycle() -> int:
    try:
        return max(1, int((os.getenv("TRADING_MAX_BUYS_PER_CYCLE") or "1").strip()))
    except ValueError:
        return 1


def _held_weight_ratio(balance: dict[str, Any], symbol: str) -> float | None:
    from trading_validator import symbol_value_ratio_in_portfolio

    return symbol_value_ratio_in_portfolio(balance, symbol)


def collect_buy_candidate(
    sym: str,
    *,
    balance: dict[str, Any],
    sizing_nav: float,
    rulebook: Rulebook,
    ec: EngineConfig,
    snap: Any,
    vix_f: float | None,
    risk_off: bool,
    vix_spike: bool,
    adaptive_out: Any,
    use_pipeline: bool,
    regime_enum: MarketRegime,
    rs_pct: float | None,
    client: KISClient | None,
    blocked: dict[str, str],
    skip_buy_if_held: bool,
    held_qty_fn: Any,
    allow_topup: bool = False,
    pipeline_info: Callable[[str, str, bool, str], None] | None = None,
    buy_attempts: dict[str, dict[str, Any]] | None = None,
    position_state: dict[str, dict[str, Any]] | None = None,
) -> BuyCandidate | None:
    def pipe(step: str, blocked_step: bool, reason: str) -> None:
        if pipeline_info is not None:
            pipeline_info(sym, step, blocked_step, reason)

    if is_symbol_blocked(sym, blocked):
        print(f"SKIP {sym}: 재진입 차단 중")
        return None
    held_q = int(held_qty_fn(balance, sym))
    is_topup = held_q > 0 and allow_topup

    cool = buy_skip_reason(
        sym,
        buy_attempts=buy_attempts,
        position_state=position_state,
        allow_topup=is_topup,
    )
    if cool:
        pipe("buy_cooldown", True, cool)
        print(f"SKIP {sym}: {cool}")
        return None

    max_pct = rulebook.position.max_single_name_pct_fund_style
    weight = _held_weight_ratio(balance, sym) if held_q > 0 else None

    if held_q > 0:
        if allow_topup:
            if weight is not None and weight >= max_pct:
                pipe(
                    "name_weight",
                    True,
                    f"비중 {weight * 100:.1f}% ≥ 상한 {max_pct * 100:.0f}%",
                )
                print(
                    f"SKIP {sym}: 비중 상한 도달 "
                    f"({weight * 100:.1f}% ≥ {max_pct * 100:.0f}%)"
                )
                return None
        elif skip_buy_if_held:
            print(f"SKIP {sym}: 이미 보유 중")
            return None

    decision, stock_ctx, ref_src = evaluate_entry_score(
        sym,
        snap=snap,
        vix_f=vix_f,
        risk_off=risk_off,
        vix_spike=vix_spike,
        adaptive_out=adaptive_out,
        use_pipeline=use_pipeline,
        regime_enum=regime_enum,
        client=client,
        rs_pct=rs_pct,
    )
    entry_px, _ = get_entry_reference_price(sym, stock_ctx, client=client)
    if decision is None:
        ws = stock_ctx.get("warnings") or []
        wh = ",".join(str(x) for x in (list(ws)[:3])) if isinstance(ws, list) and ws else "-"
        pipe("fdr_snapshot", True, f"기준가없음 warnings={wh}")
        print(f"SKIP {sym}: {ref_src}")
        return None
    pipe("fdr_snapshot", False, f"ref={ref_src} px≈{entry_px:,.0f}원")
    if decision.tier == "skip" or decision.position_fraction <= 0:
        pipe("entry_score", True, (decision.explanation or "")[:220])
        print(f"SKIP {sym}: 통합점수 tier=skip — {decision.explanation[:120]}")
        return None
    if is_topup and decision.tier != "full":
        pipe("entry_score", True, f"비중확대는 full만 tier={decision.tier}")
        print(f"SKIP {sym}: 비중확대는 tier=full만 — 현재 {decision.tier}")
        return None
    pipe(
        "entry_score",
        False,
        f"tier={decision.tier} combined={decision.signal_adjusted:.1f}",
    )
    tier_score = decision.signal_adjusted

    base_risk = rulebook.position.max_portfolio_risk_per_trade_pct
    risk_pct = base_risk * decision.position_fraction * decision.size_multiplier
    atr_buy_m = 1.0
    if adaptive_out is not None:
        try:
            from configs.adaptive_regime import AdaptiveRegimeConfig
            from regime_engine import atr_hard_stop_multiplier, load_adaptive_regime_config_from_env

            cfg_a = load_adaptive_regime_config_from_env(AdaptiveRegimeConfig())
            arv = stock_ctx.get("atr_ratio")
            atr_buy_m = atr_hard_stop_multiplier(float(arv) if arv is not None else None, cfg_a)
        except Exception:
            atr_buy_m = 1.0
    stop_px = entry_px * (1.0 - rulebook.sell.hard_stop_loss_pct * atr_buy_m)
    rt_fee = commission_round_trip_kr(ec)
    qty = shares_from_portfolio_risk(
        sizing_nav, entry_px, stop_px, risk_pct, round_trip_commission_frac=rt_fee
    )
    from trading_validator import portfolio_nav_krw, symbol_holding_value_krw

    nav_cap = portfolio_nav_krw(balance)
    if nav_cap <= 0:
        nav_cap = sizing_nav
    max_val = nav_cap * max_pct
    if is_topup and entry_px > 0:
        held_val = symbol_holding_value_krw(balance, sym)
        room = max(0.0, max_val - held_val)
        topup_sh = int(room // entry_px)
        if topup_sh < 1:
            pipe("sizing_qty", True, f"20%까지 여유 없음 held={held_val:.0f} nav={nav_cap:.0f}")
            print(f"SKIP {sym}: 비중 확대 여유 없음 (현재 {weight * 100:.1f}%)" if weight else f"SKIP {sym}: 비중 확대 여유 없음")
            return None
        qty = min(qty, topup_sh)
        pipe(
            "sizing_qty",
            False,
            f"topup≤{topup_sh}주 room≈{room:,.0f}원 비중={(weight or 0) * 100:.1f}%",
        )
    else:
        cap_sh = int(max_val // entry_px) if entry_px > 0 else 0
        if cap_sh > 0:
            qty = min(qty, cap_sh)
    fo = int((os.getenv("FORCE_ORDER_QTY") or "0").strip() or "0")
    if fo > 0:
        qty = min(qty, fo)
    qty = max(qty, 0)
    if qty <= 0:
        pipe(
            "sizing_qty",
            True,
            f"risk={risk_pct:.4f} entry={entry_px:.0f} stop={stop_px:.0f}",
        )
        print(f"SKIP {sym}: 사이징 0주")
        return None
    pipe("sizing_qty", False, f"{qty}주 risk={risk_pct:.4f} ref={ref_src}")
    try:
        intent = OrderIntent(symbol=sym, qty=qty)
        sym, qty = intent.symbol, intent.qty
    except Exception as exc:
        print(f"SKIP {sym}: intent {exc}")
        return None

    return BuyCandidate(
        symbol=sym,
        score=tier_score,
        qty=qty,
        decision=decision,
        stock_ctx=stock_ctx,
        entry_px=entry_px,
        stop_px=stop_px,
        ref_source=ref_src,
        is_topup=is_topup,
    )


def collect_held_topup_candidates(
    holdings: list[dict[str, Any]],
    *,
    balance: dict[str, Any],
    sizing_nav: float,
    rulebook: Rulebook,
    ec: EngineConfig,
    snap: Any,
    vix_f: float | None,
    risk_off: bool,
    vix_spike: bool,
    adaptive_out: Any,
    use_pipeline: bool,
    regime_enum: MarketRegime,
    client: KISClient | None,
    blocked: dict[str, str],
    held_qty_fn: Any,
    pipeline_info: Callable[[str, str, bool, str], None] | None = None,
    buy_attempts: dict[str, dict[str, Any]] | None = None,
    position_state: dict[str, dict[str, Any]] | None = None,
) -> list[BuyCandidate]:
    """보유 종목 비중 상한 미만 + 매수조건 충족 시 확대 후보."""
    if not allow_held_topup_enabled() or not holdings:
        return []
    out: list[BuyCandidate] = []
    for row in holdings:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("pdno", "")).strip()
        if not sym or held_qty_fn(balance, sym) <= 0:
            continue
        cand = collect_buy_candidate(
            sym,
            balance=balance,
            sizing_nav=sizing_nav,
            rulebook=rulebook,
            ec=ec,
            snap=snap,
            vix_f=vix_f,
            risk_off=risk_off,
            vix_spike=vix_spike,
            adaptive_out=adaptive_out,
            use_pipeline=use_pipeline,
            regime_enum=regime_enum,
            rs_pct=None,
            client=client,
            blocked=blocked,
            skip_buy_if_held=False,
            held_qty_fn=held_qty_fn,
            allow_topup=True,
            pipeline_info=pipeline_info,
            buy_attempts=buy_attempts,
            position_state=position_state,
        )
        if cand is not None:
            out.append(cand)
    return out
