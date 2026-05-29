"""
한 사이클 자동매매 진입점.

실제 매도 판단은 trade_runner → trade_ops.evaluate_holding_sell()
→ trading_rules.sell_decision.evaluate_sell() 경로를 사용합니다.
position_state: logs/position_state.json (tp1_done / tp2_done 포함)
"""
from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

from safe_logging import get_safe_logger
from secure_env import validate_kis_credentials
from trade_ops import evaluate_holding_sell
from trade_runner import run_trading_cycle, to_bool

_log = get_safe_logger(__name__)

# auto_trade / 외부 스크립트에서 매도 판단 재사용
evaluate_sell_for_holding = evaluate_holding_sell


def run_once(dry_run: bool, test_symbol: str, test_qty: int) -> int: