#!/usr/bin/env python3
"""규칙·엔진 설정 요약 + 스코어 파이프라인 샘플."""
import argparse
import json
import sys
from dataclasses import asdict

from dotenv import load_dotenv

from trading_rules import MarketRegimeSnapshot, SignalComponents, decide_entry, get_engine_config, get_rulebook


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo-score", action="store_true", help="충돌 해결 데모 출력")
    args = parser.parse_args()

    load_dotenv(".env")
    rb = get_rulebook()
    ec = get_engine_config()

    out: dict = {
        "hard_stop_pct": rb.sell.hard_stop_loss_pct,
        "score_thresholds": asdict(ec.score_thresholds),
        "score_weights": asdict(ec.score_weights),
        "conflict_policy": asdict(ec.conflict),
        "max_portfolio_heat": ec.portfolio_heat.max_total_open_risk_pct,
        "daily_max_loss_pct": ec.daily_risk.max_daily_loss_pct,
    }

    if args.demo_score:
        snap = MarketRegimeSnapshot(
            kospi_above_ma20=True,
            kospi_above_ma60=True,
            nasdaq_uptrend=True,
            foreign_net_buying_sustained=True,
            vix_spike=True,
        )
        comp = SignalComponents(trend=92.0, volume=88.0, regime=50.0, sector=75.0, liquidity=70.0)
        d = decide_entry(
            snap,
            comp,
            vix_level=34.0,
            risk_off=True,
            vix_spike=True,
            is_high_stock_vol=True,
            symbol="DEMO",
        )
        out["demo"] = {
            "tier": d.tier,
            "position_fraction": d.position_fraction,
            "signal_raw": d.signal_raw,
            "signal_adjusted": d.signal_adjusted,
            "regime_score": d.regime_score,
            "regime_label": d.regime_label,
            "conflict_reasons": list(d.conflict_reasons),
            "size_multiplier": d.size_multiplier,
            "explanation": d.explanation,
        }

    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
