"""
국내 한 사이클 자동매매 (한 바퀴 = 아래 순서).

1) 유니버스 후보 스캔: `resolve_candidate_symbols` (AUTO_SCAN / AUTO_TRADE_SYMBOLS 등)
2) 보유 종목 규칙 매도 후보 → 조건 충족 시 매도 주문 (`AUTO_RUN_SELLS`)
3) 매수: 슬롯 여유 시 후보 순회·엔진+TA 점수 → 상위 N종 매수
   슬롯 만석(`MAX_OPEN_POSITIONS`) 시 `TRADING_SCAN_HELD_ENTRY` 로 보유만 [보유진단] 재평가
4) 실매매 매수 직후 텔레그램: 주문 응답 + (가능 시) 당일 체결 조회 (`TELEGRAM_POST_BUY_REPORT`)

주기 실행은 `market_watch.py` + `.env` 의 `TRADING_WATCH=true` + `TRADING_WATCH_INTERVAL_SEC`(기본 60).

- 수수료는 `EngineConfig.commission` (기본 KR 0.147%, US 0.25% per leg) → 사이징에 왕복 반영
- 미국 현물 자동 주문 API는 미연결 (`AUTO_MARKET=KR`만 실행)
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from daily_min_trade import (
    bump_orders_today,
    force_daily_after_hour_kst,
    force_daily_trade_enabled,
    kst_hour,
    live_force_allowed,
    needs_min_orders_today,
    orders_today,
)
from kis_client import KISClient
from reporting import (
    append_trade_journal,
    format_ccld_rows,
    format_kis_fill_telegram,
    order_output_odno,
    poll_order_fill,
)
from safe_logging import get_safe_logger
from secure_env import (
    validate_kis_credentials,
    validate_live_order_confirm,
    validate_telegram_if_enabled,
)
from snapshot_filler import fetch_equity_context_fdr, fill_market_regime_snapshot_fdr, krx_display_name
from telegram_notify import clear_fail_telegram_dedup, send_telegram, send_telegram_fail_once
from trading_rules.engine_config import EngineConfig
from trade_ops import (
    BuyCandidate,
    allow_rebuy_after_sell,
    block_symbol_reentry,
    clear_buy_attempt,
    allow_held_topup_enabled,
    collect_buy_candidate,
    collect_held_topup_candidates,
    compute_kr_market_breadth_cached,
    holding_entry_scan_enabled,
    scan_held_positions_entry,
    get_entry_reference_price,
    load_blocked_symbols,
    load_buy_attempt_state,
    load_position_state,
    log_holdings_summary,
    max_buys_per_cycle,
    place_order,
    record_buy_attempt,
    register_position_entry,
    remove_position,
    save_buy_attempt_state,
    save_position_state,
    apply_sell_decision_to_position,
    entry_risk_off_cap_flag,
    evaluate_holding_sell,
    sell_qty_for_ratio,
    sell_reasons,
    trading_order_type,
    update_highest_px,
)
from trading_rules.loader import get_engine_config, get_rulebook
from trading_rules.models import MarketRegime, Rulebook, classify_regime
from trading_rules.risk_limits import portfolio_heat_ok
from trading_validator import validate_buy_order
from universe_scan import describe_source, resolve_candidate_symbols
from validated_inputs import OrderIntent

_log = get_safe_logger(__name__)


def _kis_rt_ok(rt: str) -> bool:
    s = (rt or "").strip()
    return s in {"0", "00"}


def _pipeline_info(tag: str, step: str, blocked: bool, reason: str) -> None:
    status = "BLOCK" if blocked else "PASS"
    _log.info("[PIPELINE] %s | 단계=%-12s | %s | 이유: %s", tag, step, status, reason)


def to_bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _parse_float(x: Any) -> float:
    try:
        return float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _portfolio_nav_krw(balance: dict[str, Any]) -> float:
    o2 = balance.get("output2")
    if not isinstance(o2, list) or not o2:
        return 0.0
    row0 = o2[0]
    if not isinstance(row0, dict):
        return 0.0
    return _parse_float(row0.get("nass_amt"))


def _sizing_nav_krw(*, dry_run: bool, balance: dict[str, Any]) -> tuple[float, float]:
    """
    (사이징에 쓸 금액, KIS 실순자산 nass_amt).

    TRADING_SIZING_NAV_KRW 미설정·0·비파싱: 잔고 기준 실순자산만 사용.
    설정값이 TRADING_SIZING_NAV_USE_REAL_BELOW_KRW 미만이고 KIS 실순자산>0이면
    (너무 작은 페이퍼 NAV로 인한 0주 방지) 사이징에 실순자산을 쓴다.
    그 외: 드라이런=설정값, 실매매=min(실순자산, 설정값).
    """
    real = _portfolio_nav_krw(balance)
    raw = (os.getenv("TRADING_SIZING_NAV_KRW") or "").strip().replace(",", "")
    if not raw:
        if real <= 0:
            _log.warning(
                "[사이징NAV] TRADING_SIZING_NAV_KRW 미설정·KIS nass_amt≤0 — 사이징 기준 0원"
            )
        return real, real
    try:
        target = float(raw)
    except ValueError:
        return real, real
    if target <= 0:
        return real, real

    try:
        floor_use_real = int((os.getenv("TRADING_SIZING_NAV_USE_REAL_BELOW_KRW") or "500000").strip())
    except ValueError:
        floor_use_real = 500_000
    if floor_use_real > 0 and target < float(floor_use_real) and real > 0:
        _log.info(
            "[사이징NAV] TRADING_SIZING_NAV_KRW=%.0f < %d원 임계 → KIS순자산 %.0f원으로 사이징",
            target,
            floor_use_real,
            real,
        )
        return real, real

    if dry_run:
        return target, real
    if real <= 0:
        _log.warning(
            "[사이징NAV] KIS nass_amt≤0 — TRADING_SIZING_NAV_KRW=%.0f원으로 폴백(실매매)",
            target,
        )
        return target, real
    return min(real, target), real


def _domestic_holdings(balance: dict[str, Any]) -> list[dict[str, Any]]:
    o1 = balance.get("output1")
    if not isinstance(o1, list):
        return []
    out: list[dict[str, Any]] = []
    for row in o1:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("pdno", "")).strip()
        if not sym:
            continue
        q = int(_parse_float(row.get("hldg_qty", 0)))
        if q <= 0:
            continue
        out.append(row)
    return out


def _sellable_qty(row: dict[str, Any]) -> int:
    """KIS 주문가능수량(ord_psbl_qty) 우선 — 미체결·당일매도 후 hldg만 남는 경우 방지."""
    hldg = int(_parse_float(row.get("hldg_qty", 0)))
    if hldg <= 0:
        return 0
    psbl_raw = row.get("ord_psbl_qty")
    if psbl_raw is not None and str(psbl_raw).strip() != "":
        psbl = int(_parse_float(psbl_raw))
        return max(0, min(psbl, hldg))
    return hldg


def _is_sell_qty_exceeded_error(exc: BaseException) -> bool:
    msg = str(exc)
    return "APBK0400" in msg or "주문 가능한 수량" in msg


def _pnl_fraction_from_row(row: dict[str, Any]) -> float:
    """KIS 평가손익률(%) → 소수."""
    rt = row.get("evlu_pfls_rt")
    if rt is None or str(rt).strip() == "":
        return 0.0
    return _parse_float(rt) / 100.0


def _holding_days_from_row(row: dict[str, Any]) -> int:
    raw = row.get("pchs_dt") or row.get("buy_dt") or row.get("pchs_stt_dt")
    if raw is None:
        return 0
    s = str(raw).strip()
    if len(s) != 8 or not s.isdigit():
        return 0
    try:
        d0 = datetime.strptime(s, "%Y%m%d").date()
        return (datetime.now().date() - d0).days
    except ValueError:
        return 0


def _open_position_count(balance: dict[str, Any]) -> int:
    return len(_domestic_holdings(balance))


def _portfolio_heat_fraction_estimate(
    balance: dict[str, Any],
    *,
    nav: float,
    hard_stop_loss_pct: float,
    extra_notional_krw: float,
) -> float | None:
    """보유 평가×하드스탑비율 + 신규 명목×하드스탑 추정 위험액 / 순자산."""
    if nav <= 0:
        return None
    o1 = balance.get("output1")
    if not isinstance(o1, list):
        return None
    hs = max(0.0, hard_stop_loss_pct)
    risk_krw = max(0.0, extra_notional_krw) * hs
    for row in o1:
        if not isinstance(row, dict):
            continue
        if int(_parse_float(row.get("hldg_qty", 0))) <= 0:
            continue
        ev = _parse_float(row.get("evlu_amt"))
        if ev > 0:
            risk_krw += ev * hs
    return risk_krw / nav


def _symbol_hold_qty(balance: dict[str, Any], symbol: str) -> int:
    sym = symbol.strip()
    for row in _domestic_holdings(balance):
        if str(row.get("pdno", "")).strip() == sym:
            return int(_parse_float(row.get("hldg_qty", 0)))
    return 0


def _candidate_symbols() -> list[str]:
    return resolve_candidate_symbols(to_bool_fn=to_bool)


def _commission_round_trip_kr(ec: EngineConfig) -> float:
    return 2.0 * max(0.0, ec.commission.kr_one_way)


def _telegram_safe(msg: str) -> None:
    try:
        send_telegram(msg)
    except Exception as exc:
        _log.warning("telegram: %s", exc)


def _post_order_fill_telegram(
    client: KISClient,
    *,
    odno: str,
    side: str,
    symbol: str,
    qty: int,
    stock_ctx: dict[str, Any] | None = None,
    name: str = "",
    trade_reason: str = "",
    fill_price_hint: float | None = None,
) -> bool:
    """
    체결 조회 후 텔레그램 발송.
    Returns: KIS API에서 ODNO 일치·체결수량>0 확인 시 True (포지션/저널 반영 허용).
    """
    _ = fill_price_hint  # 레거시 인자 — 체결 판정에 사용하지 않음
    use_kis = to_bool(os.getenv("TELEGRAM_KIS_FILL_FORMAT", "true"))
    try:
        wait_sec = max(1.0, float((os.getenv("TELEGRAM_FILL_WAIT_SEC") or "3").strip()))
    except ValueError:
        wait_sec = 3.0
    try:
        poll_n = max(1, int((os.getenv("TELEGRAM_FILL_POLL_RETRIES") or "4").strip()))
    except ValueError:
        poll_n = 4

    if not odno:
        _telegram_safe(
            f"[주문응답 알림]\n종목={symbol}\n주문번호 없음(ODNO blank)으로 체결안내 생략\n"
            "HTS/KIS 미체결·체결내역에서 직접 확인 필요"
        )
        return False

    try:
        confirmed = poll_order_fill(client, odno, wait_sec=wait_sec, poll_n=poll_n)
        if not confirmed:
            _telegram_safe(
                f"[주문접수/미체결 확인필요]\n종목={symbol}\n주문번호={odno}\n"
                "체결조회에서 일치 체결을 확인하지 못했습니다.\n"
                "HTS/KIS 체결·미체결 화면을 확인해 주세요."
            )
            return False

        if not use_kis:
            today = datetime.now().strftime("%Y%m%d")
            fills = client.inquire_daily_ccld(today, today, ccld_dvsn="01", odno=odno)
            _telegram_safe(
                format_ccld_rows(fills, title=f"[당일 체결] ODNO={odno}", max_rows=25)
            )
            return True

        today = datetime.now().strftime("%Y%m%d")
        fills = client.inquire_daily_ccld(today, today, ccld_dvsn="01", odno=odno)
        nm = (name or "").strip()
        if not nm and stock_ctx:
            nm = str(stock_ctx.get("name_kr") or stock_ctx.get("prdt_name") or "").strip()
        if not nm:
            nm = krx_display_name(symbol).strip()
        _telegram_safe(
            format_kis_fill_telegram(
                fills,
                odno=odno,
                side=side,
                symbol=symbol,
                stock_name=nm,
                trade_reason=trade_reason,
            )
        )
        return True
    except Exception as exc:
        _telegram_safe(f"[체결 조회 경고]\n{exc!s}")
        return False


def _telegram_fail_once_safe(kind: str, symbol: str, msg: str) -> None:
    """검증/주문 실패 알림 — 동일 종목·종류·당일 1회(TELEGRAM_FAIL_ALERT_DEDUP)."""
    try:
        send_telegram_fail_once(kind, symbol, msg)
    except Exception as exc:
        _log.warning("telegram: %s", exc)


def _tg_stock(sym: str, *, name: str | None = None, stock_ctx: dict[str, Any] | None = None) -> str:
    """텔레그램용: 코드 + 종목명(가능할 때)."""
    n = (name or "").strip()
    if not n and stock_ctx:
        n = str(stock_ctx.get("name_kr") or stock_ctx.get("prdt_name") or "").strip()
    if not n:
        n = krx_display_name(sym).strip()
    return f"{sym} {n}".strip() if n else sym


def _max_open_positions() -> int:
    return int(float((os.getenv("MAX_OPEN_POSITIONS") or "5").strip() or "5"))


def run_trading_cycle(*, dry_run: bool) -> int:
    start_time = time.time()
    cycle_log: list[str] = []
    nav_real_box: list[float | None] = [None]
    nav_sizing_box: list[float | None] = [None]
    cycle_stats: dict[str, int] = {
        "scan_n": 0,
        "sell_reviewed": 0,
        "buy_reviewed": 0,
        "executed": 0,
        "skip_sizing0": 0,
        "skip_score": 0,
    }

    def note(msg: str) -> None:
        cycle_log.append(msg)

    def finish(code: int) -> int:
        elapsed = time.time() - start_time
        _log.info(
            "[CYCLE DONE] 스캔=%d 매도검토=%d 매수검토=%d 실행=%d 스킵(사이징0)=%d 스킵(스코어)=%d 소요=%.1fs",
            cycle_stats["scan_n"],
            cycle_stats["sell_reviewed"],
            cycle_stats["buy_reviewed"],
            cycle_stats["executed"],
            cycle_stats["skip_sizing0"],
            cycle_stats["skip_score"],
            elapsed,
        )
        if to_bool(os.getenv("TELEGRAM_CYCLE_REPORT", "false")):
            lines = [
                "[자동매매·사이클 요약]" + (" ·DRY_RUN" if dry_run else ""),
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ]
            if nav_real_box[0] is not None:
                lines.append(f"KIS순자산≈{nav_real_box[0]:,.0f}원")
            if nav_sizing_box[0] is not None:
                lines.append(f"사이징기준≈{nav_sizing_box[0]:,.0f}원")
            if cycle_log:
                lines.append("—")
                lines.extend(cycle_log)
            else:
                lines.append("(이번 실행에서 기록된 매매 이벤트 없음)")
            _telegram_safe("\n".join(lines))
        if to_bool(os.getenv("DASHBOARD_AUTO_SYNC", "false")):
            try:
                from holdings_quotes import sync_holdings_quotes

                sync_holdings_quotes()
            except Exception as exc:
                _log.debug("dashboard sync: %s", exc)
        return code

    granular_dry_tg = to_bool(os.getenv("TELEGRAM_DRY_RUN_VALIDATION", "false")) and not to_bool(
        os.getenv("TELEGRAM_CYCLE_REPORT", "false")
    )
    notify_pick_dry = to_bool(os.getenv("TELEGRAM_NOTIFY_PICK_DRY_RUN", "false"))
    post_buy_telegram = to_bool(os.getenv("TELEGRAM_POST_BUY_REPORT", "true"))

    if not dry_run:
        _log.warning(
            "실매매 모드: 조건 충족 시 국내 현금 매도·매수가 KIS로 전송됩니다."
        )

    market = (os.getenv("AUTO_MARKET") or "KR").strip().upper()
    if market != "KR":
        _log.error("AUTO_MARKET=%s — 현재 국내(KR) 자동 주문만 지원합니다.", market)
        print(f"FAILED: AUTO_MARKET={market} (only KR wired for live orders)")
        note(f"중단: AUTO_MARKET={market} (KR만 지원)")
        return finish(1)

    symbols = _candidate_symbols()
    if not symbols:
        print("FAILED: no symbols (AUTO_TRADE_SYMBOLS or TEST_SYMBOL)")
        note("중단: 후보 종목 없음")
        return finish(1)

    try:
        intents = [OrderIntent(symbol=s, qty=1) for s in symbols]
        symbols = [i.symbol for i in intents]
    except Exception as exc:
        print(f"FAILED: symbol validation {exc}")
        note(f"중단: 종목코드 검증 실패 ({exc})")
        return finish(1)

    rs_pct_by_symbol: dict[str, float] = {}
    if to_bool(os.getenv("USE_RS_RANKING", "false")):
        try:
            from factors.fdr_rank import rank_universe_fdr

            sym_ranked, detail = rank_universe_fdr(symbols)
            if sym_ranked:
                symbols = sym_ranked
            if not detail.empty:
                rs_pct_by_symbol = {
                    str(r.symbol): float(r.rs_percentile)
                    for r in detail.itertuples(index=False)
                    if hasattr(r, "rs_percentile") and r.rs_percentile == r.rs_percentile
                }
            print("RS_RANK: candidates reordered by composite momentum (FDR)")
        except Exception as exc:
            _log.warning("USE_RS_RANKING skipped: %s", exc)

    cycle_stats["scan_n"] = len(symbols)

    if not dry_run:
        try:
            validate_live_order_confirm()
            validate_telegram_if_enabled()
        except Exception as exc:
            _log.error("Live precheck failed: %s", exc)
            print(f"FAILED: {exc}")
            note(f"중단: 라이브 사전검증 ({exc})")
            return finish(1)

    try:
        client = KISClient()
    except Exception as exc:
        _log.error("Auth init failed: %s", exc)
        print(f"FAILED: auth init ({exc})")
        note(f"중단: KIS 인증 ({exc})")
        return finish(1)

    try:
        balance = client.inquire_balance()
    except Exception as exc:
        _log.error("Balance inquiry failed: %s", exc)
        print(f"FAILED: balance ({exc})")
        note(f"중단: 잔고조회 ({exc})")
        return finish(1)

    sizing_nav, real_nav = _sizing_nav_krw(dry_run=dry_run, balance=balance)
    nav_real_box[0] = real_nav
    nav_sizing_box[0] = sizing_nav
    log_holdings_summary(balance)
    pos_state = load_position_state()
    blocked_symbols = load_blocked_symbols()
    buy_attempts = load_buy_attempt_state()
    note(
        f"후보출처={describe_source()} 수={len(symbols)} "
        f"예시={','.join(symbols[:10])}{'...' if len(symbols) > 10 else ''}"
    )

    rulebook = get_rulebook()
    ec = get_engine_config()
    snap, snap_meta = fill_market_regime_snapshot_fdr(rulebook.regime)
    vix_level = snap_meta.get("vix_close")
    vix_f = float(vix_level) if isinstance(vix_level, (int, float)) else None

    run_sells = to_bool(os.getenv("AUTO_RUN_SELLS", "true"))
    skip_buy_if_held = to_bool(os.getenv("SKIP_BUY_IF_HELD", "true"))
    use_pipeline = to_bool(os.getenv("USE_ENTRY_PIPELINE", "true"))

    adaptive_out: Any = None
    if to_bool(os.getenv("USE_ADAPTIVE_REGIME", "false")):
        try:
            from configs.adaptive_regime import AdaptiveRegimeConfig
            from regime_engine import (
                RegimeEnginePersistentState,
                compute_adaptive_regime,
                fetch_market_series_fdr,
                load_adaptive_regime_config_from_env,
            )
            from trading_rules.regime_score import infer_regime_features_from_snapshot

            vx_s, kc_s, kv_s = fetch_market_series_fdr()
            feats_ad = infer_regime_features_from_snapshot(snap, vix_level=vix_f)
            cfg_ad = load_adaptive_regime_config_from_env(AdaptiveRegimeConfig())
            state_path = Path(
                (os.getenv("ADAPTIVE_REGIME_STATE_PATH") or "logs/adaptive_regime_state.json").strip()
            )
            st_ad: RegimeEnginePersistentState | None = None
            if state_path.exists():
                st_ad = RegimeEnginePersistentState.from_dict(json.loads(state_path.read_text()))
            adaptive_out, st_out = compute_adaptive_regime(
                vix=vx_s,
                kospi_close=kc_s,
                kospi_volume=kv_s,
                feats=feats_ad,
                engine_cfg=ec,
                rulebook_regime=rulebook.regime,
                cfg=cfg_ad,
                state=st_ad,
                stock_atr_ratio=None,
            )
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps(st_out.to_dict(), indent=0))
            print(
                f"ADAPTIVE_REGIME vol={adaptive_out.volatility_regime} "
                f"trend={adaptive_out.trend_regime} liq={adaptive_out.liquidity_regime} "
                f"vix_pct={adaptive_out.vix_percentile:.2f} score_sm={adaptive_out.regime_score_smoothed:.1f}"
            )
        except Exception as exc:
            _log.warning("USE_ADAPTIVE_REGIME failed: %s", exc)
            adaptive_out = None

    if run_sells:
        for row in list(_domestic_holdings(balance)):
            sym = str(row.get("pdno", "")).strip()
            qty = _sellable_qty(row)
            if qty <= 0:
                continue
            cycle_stats["sell_reviewed"] += 1
            stock_ctx = fetch_equity_context_fdr(sym)
            if sym not in pos_state:
                avg_px = _parse_float(
                    row.get("pchs_avg_pric") or row.get("pchs_unpr") or row.get("avg_prvs") or 0
                )
                if avg_px > 0:
                    register_position_entry(pos_state, sym, avg_px)
            cur_px, _ = get_entry_reference_price(sym, stock_ctx, client=client)
            if cur_px > 0:
                update_highest_px(pos_state, sym, cur_px)
            pos_row = pos_state.get(sym) or {}
            decision = evaluate_holding_sell(
                row,
                rulebook,
                stock_ctx,
                position=pos_row,
                current_price=cur_px if cur_px > 0 else None,
            )
            if decision.action == "hold":
                continue

            sell_qty = sell_qty_for_ratio(qty, decision.sell_ratio)
            if sell_qty > qty:
                _log.info(
                    "[SELL] %s 수량 조정 %d→%d (주문가능 hldg=%s psbl=%s)",
                    sym,
                    sell_qty,
                    qty,
                    row.get("hldg_qty"),
                    row.get("ord_psbl_qty"),
                )
                sell_qty = qty
            if sell_qty <= 0:
                if int(_parse_float(row.get("hldg_qty", 0))) > 0:
                    _log.info(
                        "[SELL] %s 스킵 — 보유수량은 있으나 주문가능 0 (체결대기·이미 매도)",
                        sym,
                    )
                continue

            reason_txt = decision.reason
            is_hard_stop = decision.action == "hard_stop"
            is_ta_sell = decision.action == "ta_sell"
            name = str(row.get("prdt_name", "") or "").strip()
            disp = _tg_stock(sym, name=name)
            _log.warning(
                "[SELL] %s %s %.0f%% %s주 | %s",
                sym,
                decision.action,
                decision.sell_ratio * 100.0,
                sell_qty,
                reason_txt,
            )
            print(
                f"[SELL] {sym} {decision.action} {decision.sell_ratio * 100:.0f}% "
                f"{sell_qty}주 | {reason_txt}"
            )
            if dry_run:
                if granular_dry_tg:
                    _telegram_safe(
                        f"[DRY_RUN 매도]\n종목={disp}\n{decision.action} "
                        f"{decision.sell_ratio * 100:.0f}% {sell_qty}주\n{reason_txt}"
                    )
                note(
                    f"매도·모의 {sym} {decision.action} {sell_qty}주 | {reason_txt}"
                )
                apply_sell_decision_to_position(pos_state, sym, decision)
                if decision.sell_ratio >= 1.0:
                    remove_position(pos_state, sym)
                if decision.sell_ratio >= 1.0:
                    block_symbol_reentry(sym)
                elif allow_rebuy_after_sell():
                    clear_buy_attempt(sym, buy_attempts)
                continue
            ref_sell = cur_px if cur_px > 0 else _parse_float(stock_ctx.get("last_close") or 0.0)
            try:
                result = place_order(
                    client,
                    side="sell",
                    symbol=sym,
                    qty=sell_qty,
                    reference_price=ref_sell,
                )
            except Exception as exc:
                _log.error("Sell order failed %s: %s", sym, exc)
                if _is_sell_qty_exceeded_error(exc):
                    note(
                        f"매도·스킵 {sym}: 주문가능수량 없음 "
                        f"(잔고표기 hldg={row.get('hldg_qty')} psbl={row.get('ord_psbl_qty')})"
                    )
                    _log.warning(
                        "[SELL] %s — APBK0400 등: 실제 매도 가능 수량 없음. "
                        "HTS 잔고·미체결 확인 후 market_watch 재시작",
                        sym,
                    )
                else:
                    _telegram_fail_once_safe(
                        "sell_order_fail",
                        sym,
                        f"[매도 실패]\n종목={disp}\n{exc!s}",
                    )
                    note(f"매도·실패 {sym}: {exc!s}")
                continue
            rt = str(result.get("rt_cd") or "")
            msg1 = str(result.get("msg1") or "")
            odno = order_output_odno(result)
            journal_path = (os.getenv("JOURNAL_PATH") or "logs/trade_journal.csv").strip()
            note(
                f"매도·주문 {sym} {decision.action} {sell_qty}주 | {reason_txt} | ODNO={odno or '-'}"
            )
            if not dry_run and _kis_rt_ok(rt):
                filled = False
                if to_bool(os.getenv("TELEGRAM_POST_SELL_REPORT", "true")):
                    filled = _post_order_fill_telegram(
                        client,
                        odno=odno or "",
                        side="sell",
                        symbol=sym,
                        qty=sell_qty,
                        name=name,
                        trade_reason=reason_txt,
                    )
                elif odno:
                    try:
                        wait_sec = max(
                            1.0, float((os.getenv("TELEGRAM_FILL_WAIT_SEC") or "3").strip())
                        )
                        poll_n = max(
                            1, int((os.getenv("TELEGRAM_FILL_POLL_RETRIES") or "4").strip())
                        )
                    except ValueError:
                        wait_sec, poll_n = 3.0, 4
                    filled = (
                        poll_order_fill(client, odno, wait_sec=wait_sec, poll_n=poll_n)
                        is not None
                    )
                if filled:
                    try:
                        append_trade_journal(
                            journal_path,
                            symbol=sym,
                            qty=sell_qty,
                            odno=odno,
                            reason=f"[매도]{decision.action} {reason_txt}",
                            order_rt_cd=rt,
                            msg=msg1,
                        )
                    except Exception as exc:
                        _log.warning("Journal: %s", exc)
                    cycle_stats["executed"] += 1
                    bump_orders_today(reason="매도체결")
                    clear_fail_telegram_dedup(sym, "sell_order_fail")
                    apply_sell_decision_to_position(pos_state, sym, decision)
                    if decision.sell_ratio >= 1.0 or sell_qty >= qty:
                        remove_position(pos_state, sym)
                    if is_ta_sell:
                        try:
                            from signal_scanner.trading import mark_ta_trade

                            mark_ta_trade(sym, "sell")
                        except Exception as exc:
                            _log.debug("mark_ta_trade sell: %s", exc)
                    if decision.sell_ratio >= 1.0 or sell_qty >= qty:
                        block_symbol_reentry(sym)
                    elif allow_rebuy_after_sell():
                        clear_buy_attempt(sym, buy_attempts)
                    note(f"매도·체결확인 {sym} ODNO={odno}")
                else:
                    try:
                        append_trade_journal(
                            journal_path,
                            symbol=sym,
                            qty=sell_qty,
                            odno=odno,
                            reason=f"[매도주문·미체결]{decision.action} {reason_txt}",
                            order_rt_cd=rt,
                            msg=msg1,
                        )
                    except Exception as exc:
                        _log.warning("Journal: %s", exc)
                    note(
                        f"매도·미체결 {sym} ODNO={odno or '-'} — "
                        "포지션·재진입 상태는 변경하지 않음"
                    )
            time.sleep(1.5)

        save_position_state(pos_state)
        try:
            balance = client.inquire_balance()
        except Exception as exc:
            _log.warning("Balance refresh after sells: %s", exc)

    regime_enum, regime_reasons = classify_regime(snap, rulebook.regime, vix_level=vix_f)
    regime_risk_off = regime_enum == MarketRegime.RISK_OFF
    breadth_risk_off = False
    if to_bool(os.getenv("USE_KR_BREADTH_FILTER", "true")):
        try:
            br = compute_kr_market_breadth_cached()
            try:
                br_floor = float((os.getenv("BREADTH_RISK_OFF_BELOW") or "35").strip())
            except ValueError:
                br_floor = 35.0
            if br.score < br_floor:
                breadth_risk_off = True
                msg_br = f"BREADTH risk_off: score={br.score:.1f} < {br_floor:.0f} | {br.detail}"
                print(msg_br)
                _log.info(msg_br)
                note(msg_br)
        except Exception as exc:
            _log.warning("breadth filter skipped: %s", exc)
    risk_off_cap = entry_risk_off_cap_flag(
        regime_risk_off=regime_risk_off,
        breadth_risk_off=breadth_risk_off,
    )
    if breadth_risk_off and not risk_off_cap:
        _log.info(
            "BREADTH 약세 — 엔진 risk_off 상한 미적용 (regime=%s). "
            "구동작 상한은 TRADING_BREADTH_APPLY_RISK_OFF_CAP=true",
            regime_enum.value,
        )
    vix_spike = bool(snap.vix_spike)

    max_open = _max_open_positions()
    held_rows = _domestic_holdings(balance)
    open_n = len(held_rows)
    slots_full = open_n >= max_open

    candidates: list[BuyCandidate] = []
    if allow_held_topup_enabled() and held_rows:
        for row in held_rows:
            cycle_stats["buy_reviewed"] += 1
        topup_list = collect_held_topup_candidates(
            held_rows,
            balance=balance,
            sizing_nav=sizing_nav,
            rulebook=rulebook,
            ec=ec,
            snap=snap,
            vix_f=vix_f,
            risk_off=risk_off_cap,
            vix_spike=vix_spike,
            adaptive_out=adaptive_out,
            use_pipeline=use_pipeline,
            regime_enum=regime_enum,
            client=client,
            blocked=blocked_symbols,
            held_qty_fn=_symbol_hold_qty,
            pipeline_info=_pipeline_info,
            buy_attempts=buy_attempts,
            position_state=pos_state,
        )
        candidates.extend(topup_list)
        if topup_list:
            print(
                f"[비중확대] 후보 {len(topup_list)}종 — "
                + ", ".join(f"{c.symbol}({c.score:.0f})" for c in topup_list[:6])
            )

    if slots_full:
        if holding_entry_scan_enabled():
            scan_held_positions_entry(
                held_rows,
                snap=snap,
                vix_f=vix_f,
                risk_off=risk_off_cap,
                vix_spike=vix_spike,
                adaptive_out=adaptive_out,
                use_pipeline=use_pipeline,
                regime_enum=regime_enum,
                client=client,
                blocked=blocked_symbols,
                rs_pct_by_symbol=rs_pct_by_symbol,
                max_open=max_open,
            )
        if not candidates:
            msg = (
                f"SKIP_BUY: 슬롯 만석({open_n}/{max_open}) — "
                "비중확대·매수조건 충족 보유 없음"
            )
            print(msg)
            note(msg)
            save_position_state(pos_state)
            return finish(0)
        note(f"슬롯 만석 — 신규 종목 스캔 생략, 보유 비중확대만 검토")
    else:
        m_min = rulebook.fundamental.min_market_cap_krw_bn
        for sym in symbols:
            if _symbol_hold_qty(balance, sym) > 0:
                continue
            cycle_stats["buy_reviewed"] += 1
            _pipeline_info(sym, "mcap_filter", False, f"스캔·룰 동일 TRADING_MIN_MCAP_BN≥{m_min}십억")
            cand = collect_buy_candidate(
                sym,
                balance=balance,
                sizing_nav=sizing_nav,
                rulebook=rulebook,
                ec=ec,
                snap=snap,
                vix_f=vix_f,
                risk_off=risk_off_cap,
                vix_spike=vix_spike,
                adaptive_out=adaptive_out,
                use_pipeline=use_pipeline,
                regime_enum=regime_enum,
                rs_pct=rs_pct_by_symbol.get(sym),
                client=client,
                blocked=blocked_symbols,
                skip_buy_if_held=skip_buy_if_held,
                held_qty_fn=_symbol_hold_qty,
                allow_topup=False,
                pipeline_info=_pipeline_info,
                buy_attempts=buy_attempts,
                position_state=pos_state,
            )
            if cand is None:
                continue
            candidates.append(cand)

    candidates.sort(key=lambda c: c.score, reverse=True)
    slots_left = max(0, max_open - open_n)
    top_candidates: list[BuyCandidate] = []
    new_slots_used = 0
    per_cycle = max_buys_per_cycle()
    for cand in candidates:
        if cand.is_topup:
            top_candidates.append(cand)
        elif new_slots_used < slots_left:
            top_candidates.append(cand)
            new_slots_used += 1
        if len(top_candidates) >= per_cycle:
            break

    if candidates and not top_candidates:
        new_only = [c for c in candidates if not c.is_topup]
        if new_only and slots_left <= 0:
            msg_slots = (
                f"SKIP_BUY: 슬롯 없음 (보유≥{max_open}, "
                f"신규후보={len(new_only)}종)"
            )
            print(msg_slots)
            note(msg_slots)
            save_position_state(pos_state)
            return finish(0)

    if not top_candidates:
        print("NO_BUY: 후보 없음 또는 전부 스킵")
        note("매수: 후보 없음 또는 엔진/검증상 전부 스킵")
        if force_daily_trade_enabled() and needs_min_orders_today():
            gate_h = force_daily_after_hour_kst()
            kh = kst_hour()
            if kh < gate_h:
                msg = f"일일최소거래: KST {kh}시 < 트리거 {gate_h}시 — 대기 (당일주문 {orders_today()}건)"
                print(msg)
                note(msg)
                return finish(0)
            if _open_position_count(balance) >= max_open:
                msg = f"일일최소거래: 스킵 — 보유 ≥ MAX_OPEN_POSITIONS ({max_open})"
                print(msg)
                note(msg)
                _log.warning("[일일최소거래] %s", msg)
                return finish(0)
            fsym = (os.getenv("FORCE_DAILY_TRADE_SYMBOL") or os.getenv("TEST_SYMBOL") or "005930").strip()
            try:
                fqty = max(1, int((os.getenv("FORCE_DAILY_TRADE_QTY") or "1").strip() or "1"))
                fi = OrderIntent(symbol=fsym, qty=fqty)
                fsym, fqty = fi.symbol, fi.qty
            except Exception as exc:
                print(f"FORCE_DAILY_TRADE: 종목/수량 오류 {exc}")
                note(f"일일최소거래: intent 실패 {exc}")
                return finish(0)
            fctx = fetch_equity_context_fdr(fsym)
            fctx.setdefault("using_leverage", to_bool(os.getenv("USING_LEVERAGE", "false")))
            fctx.setdefault("community_chase", to_bool(os.getenv("COMMUNITY_CHASE_FLAG", "false")))
            fctx.setdefault("recent_avg_down", to_bool(os.getenv("RECENT_AVG_DOWN_FLAG", "false")))
            disp_f = _tg_stock(fsym, stock_ctx=fctx)
            ok_f, viol_f = validate_buy_order(
                symbol=fsym,
                qty=fqty,
                rulebook=rulebook,
                snapshot=snap,
                vix_level=vix_f,
                balance=balance,
                stock_ctx=fctx,
            )
            if not ok_f:
                print(f"FORCE_DAILY_TRADE: 검증 실패 {fsym} {viol_f[:3]}")
                note("일일최소거래: 검증 실패 " + "; ".join(viol_f[:5]))
                _log.warning("[일일최소거래] 검증 실패 %s %s", fsym, viol_f[:5])
                return finish(0)
            reason_f = (
                (os.getenv("TRADE_REASON") or "").strip()
                or "[일일최소거래] 엔진 후보 없음·강제 분기(KST당일 1건 이상)"
            )
            if dry_run:
                print(f"FORCE_DAILY_TRADE DRY_RUN: {fsym} qty={fqty}")
                note(f"일일최소거래·모의 {fsym} {fqty}주")
                bump_orders_today(reason="FORCE_DAILY_DRY_SIM")
                lines_f = [
                    "[DRY_RUN 일일최소거래]",
                    f"종목={disp_f} 수량={fqty}",
                    f"사유={reason_f}",
                    f"KST당일누적주문={orders_today()}건",
                ]
                if granular_dry_tg or notify_pick_dry:
                    _telegram_safe("\n".join(lines_f))
                return finish(0)
            if not live_force_allowed():
                msg = "일일최소거래: 실주문 차단 — .env 에 FORCE_DAILY_TRADE_LIVE=true 필요"
                print(msg)
                note(msg)
                _log.warning(msg)
                return finish(0)
            f_ref, _ = get_entry_reference_price(fsym, fctx, client=client)
            if f_ref <= 0:
                f_ref = _parse_float(fctx.get("last_close") or 0.0)
            try:
                res_f = place_order(
                    client,
                    side="buy",
                    symbol=fsym,
                    qty=fqty,
                    reference_price=f_ref,
                )
            except Exception as exc:
                _log.error("FORCE_DAILY_TRADE buy failed: %s", exc)
                _telegram_fail_once_safe(
                    "force_daily_buy",
                    fsym,
                    f"[일일최소거래 매수 실패]\n{disp_f}\n{exc!s}",
                )
                note(f"일일최소거래·실패 {fsym}: {exc!s}")
                return finish(1)
            rtf = str(res_f.get("rt_cd") or "")
            msgf = str(res_f.get("msg1") or "")
            odnof = order_output_odno(res_f)
            jpath = (os.getenv("JOURNAL_PATH") or "logs/trade_journal.csv").strip()
            try:
                append_trade_journal(
                    jpath,
                    symbol=fsym,
                    qty=fqty,
                    odno=odnof,
                    reason=reason_f,
                    order_rt_cd=rtf,
                    msg=msgf,
                )
            except Exception as exc:
                _log.warning("Journal: %s", exc)
            note(f"일일최소거래·주문 {fsym} {fqty}주 ODNO={odnof or '-'} rt={rtf}")
            if _kis_rt_ok(rtf):
                cycle_stats["executed"] += 1
                bump_orders_today(reason="FORCE_DAILY_BUY")
            if post_buy_telegram and _kis_rt_ok(rtf):
                _post_order_fill_telegram(
                    client,
                    odno=odnof or "",
                    side="buy",
                    symbol=fsym,
                    qty=fqty,
                    stock_ctx=fctx,
                    trade_reason=reason_f,
                )
            return finish(0)
        save_position_state(pos_state)
        return finish(0)

    rank_line = ", ".join(
        f"{c.symbol}({c.score:.1f})" for c in top_candidates[:5]
    )
    print(
        f"BUY_RANK n={len(top_candidates)} order={trading_order_type()} "
        f"max_per_cycle={max_buys_per_cycle()} | {rank_line}"
    )
    note(f"매수 후보 {len(top_candidates)}종 | {rank_line}")

    nav_for_heat = _portfolio_nav_krw(balance)
    if nav_for_heat <= 0:
        nav_for_heat = sizing_nav
    cap_h = ec.portfolio_heat.max_total_open_risk_pct
    extra_heat_nom = 0.0
    any_validate_fail = False

    for cand in top_candidates:
        sym = cand.symbol
        qty = cand.qty
        decision = cand.decision
        stock_ctx = cand.stock_ctx
        disp_buy = _tg_stock(sym, stock_ctx=stock_ctx)

        extra_nom = extra_heat_nom + qty * cand.entry_px
        heat_frac = _portfolio_heat_fraction_estimate(
            balance,
            nav=nav_for_heat,
            hard_stop_loss_pct=rulebook.sell.hard_stop_loss_pct,
            extra_notional_krw=extra_nom,
        )
        if heat_frac is None:
            _pipeline_info(sym, "port_heat", False, "순자산 미확인·추정 생략")
        elif not portfolio_heat_ok(heat_frac, ec.portfolio_heat):
            _pipeline_info(
                sym,
                "port_heat",
                True,
                f"추정={heat_frac * 100:.2f}% > 상한={cap_h * 100:.1f}%",
            )
            print(f"SKIP {sym}: portfolio heat {heat_frac * 100:.2f}% > {cap_h * 100:.1f}%")
            note(f"매수·스킵(heat) {sym}")
            continue
        else:
            _pipeline_info(
                sym,
                "port_heat",
                False,
                f"추정={heat_frac * 100:.2f}% ≤ 상한={cap_h * 100:.1f}%",
            )

        kind = "TOPUP" if cand.is_topup else "PICK"
        print(
            f"{kind} {sym} qty={qty} tier={decision.tier} adj={decision.signal_adjusted:.1f} "
            f"ref={cand.ref_source} px={cand.entry_px:.0f} {decision.explanation}"
        )
        note(
            f"엔진 PICK {sym} {qty}주 | tier={decision.tier} | adj={decision.signal_adjusted:.1f}"
        )
        ok, violations = validate_buy_order(
            symbol=sym,
            qty=qty,
            rulebook=rulebook,
            snapshot=snap,
            vix_level=vix_f,
            balance=balance,
            stock_ctx=stock_ctx,
        )
        if not ok:
            any_validate_fail = True
            _pipeline_info(sym, "buy_validate", True, "; ".join(str(v) for v in violations[:4]))
            print(f"VALIDATOR_BLOCK {sym}: {violations}")
            note(f"매수·차단 {sym} {qty}주 | " + "; ".join(violations[:5]))
            _telegram_fail_once_safe(
                "buy_validate",
                sym,
                "[매수 검증 실패]\n"
                f"종목={disp_buy} 수량={qty}\n국면={regime_enum.value}\n" + "\n".join(violations),
            )
            continue

        clear_fail_telegram_dedup(sym, "buy_validate")
        _pipeline_info(sym, "buy_validate", False, "검증통과")

        if dry_run:
            register_position_entry(pos_state, sym, cand.entry_px)
            extra_heat_nom += qty * cand.entry_px
            lines = [
                "[DRY_RUN 매수 시뮬]",
                f"종목={disp_buy} 수량={qty}",
                f"엔진={decision.explanation}",
                f"기준가={cand.entry_px:.0f}({cand.ref_source}) 주문={trading_order_type()}",
                f"수수료왕복={_commission_round_trip_kr(ec) * 100:.3f}% (반영 사이징)",
            ]
            note(
                f"매수·모의 PICK {sym} {qty}주 | tier={decision.tier} | "
                f"adj={decision.signal_adjusted:.1f}"
            )
            if granular_dry_tg or notify_pick_dry:
                _telegram_safe("\n".join(lines))
            continue

        reason = (os.getenv("TRADE_REASON") or "").strip() or "(TRADE_REASON 미설정)"
        reason = (
            f"{reason}\n[엔진] {decision.explanation}\n"
            f"기준가={cand.entry_px:.0f}({cand.ref_source}) 주문={trading_order_type()}\n"
            f"왕복수수료율≈{_commission_round_trip_kr(ec) * 100:.3f}% 반영 사이징"
        )

        try:
            result = place_order(
                client,
                side="buy",
                symbol=sym,
                qty=qty,
                reference_price=cand.entry_px,
            )
        except Exception as exc:
            _log.error("Buy failed: %s", exc)
            save_buy_attempt_state(buy_attempts)
            _telegram_fail_once_safe("buy_order_fail", sym, f"[매수 실패]\n{disp_buy} {exc!s}")
            note(f"매수·실패 {sym}: {exc!s}")
            continue

        rt = str(result.get("rt_cd") or "")
        msg1 = str(result.get("msg1") or "")
        odno = order_output_odno(result)
        journal_path = (os.getenv("JOURNAL_PATH") or "logs/trade_journal.csv").strip()

        note(f"매수·주문응답 {sym} {qty}주 | ODNO={odno or '-'} | rt_cd={rt}")
        if _kis_rt_ok(rt) and not dry_run:
            filled = False
            if post_buy_telegram:
                filled = _post_order_fill_telegram(
                    client,
                    odno=odno or "",
                    side="buy",
                    symbol=sym,
                    qty=qty,
                    stock_ctx=stock_ctx,
                    trade_reason=reason,
                )
            elif odno:
                try:
                    wait_sec = max(
                        1.0, float((os.getenv("TELEGRAM_FILL_WAIT_SEC") or "3").strip())
                    )
                    poll_n = max(1, int((os.getenv("TELEGRAM_FILL_POLL_RETRIES") or "4").strip()))
                except ValueError:
                    wait_sec, poll_n = 3.0, 4
                filled = poll_order_fill(client, odno, wait_sec=wait_sec, poll_n=poll_n) is not None
            if filled:
                try:
                    append_trade_journal(
                        journal_path,
                        symbol=sym,
                        qty=qty,
                        odno=odno,
                        reason=reason,
                        order_rt_cd=rt,
                        msg=msg1,
                    )
                except Exception as exc:
                    _log.warning("Journal: %s", exc)
                cycle_stats["executed"] += 1
                bump_orders_today(reason="매수체결")
                clear_fail_telegram_dedup(sym, "buy_order_fail", "buy_validate")
                record_buy_attempt(sym, success=True, state=buy_attempts)
                register_position_entry(pos_state, sym, cand.entry_px)
                try:
                    from signal_scanner.trading import mark_ta_trade, use_ta_signals

                    if use_ta_signals():
                        mark_ta_trade(sym, "buy")
                except Exception as exc:
                    _log.debug("mark_ta_trade buy: %s", exc)
                extra_heat_nom += qty * cand.entry_px
                try:
                    balance = client.inquire_balance()
                except Exception as exc:
                    _log.warning("Balance refresh after buy: %s", exc)
            else:
                try:
                    append_trade_journal(
                        journal_path,
                        symbol=sym,
                        qty=qty,
                        odno=odno,
                        reason=f"[매수주문·미체결]{reason}",
                        order_rt_cd=rt,
                        msg=msg1,
                    )
                except Exception as exc:
                    _log.warning("Journal: %s", exc)
                note(f"매수·미체결 {sym} ODNO={odno or '-'} — 포지션 등록 생략")
        if post_buy_telegram and dry_run and _kis_rt_ok(rt):
            nm = str(stock_ctx.get("name_kr") or "").strip() or krx_display_name(sym).strip()
            _telegram_safe(
                f"[DRY_RUN 매수 체결안내]\n{nm}({sym}) {qty}주\n"
                f"기준가={int(cand.entry_px)}\n{reason}"
            )
        time.sleep(1.5)

    save_position_state(pos_state)
    save_buy_attempt_state(buy_attempts)
    if dry_run and top_candidates:
        print("DRY_RUN: no buy order sent.")
    if any_validate_fail and cycle_stats["executed"] == 0 and not dry_run:
        return finish(1)
    return finish(0)


def main_cli() -> int:
    load_dotenv(".env")
    if os.getenv("SKIP_KIS_ENV_VALIDATION", "").strip().lower() not in {"1", "true", "yes"}:
        min_k = int(os.getenv("KIS_MIN_KEY_LEN", "8"))
        min_s = int(os.getenv("KIS_MIN_SECRET_LEN", "8"))
        try:
            validate_kis_credentials(min_key_len=min_k, min_secret_len=min_s)
        except Exception as exc:
            print(f"FAILED: env validation ({exc})")
            return 1

    dry_run = to_bool(os.getenv("DRY_RUN", "true"))
    return run_trading_cycle(dry_run=dry_run)


if __name__ == "__main__":
    import sys

    sys.exit(main_cli())
