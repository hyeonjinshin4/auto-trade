import os
import sys

from dotenv import load_dotenv

from auto_trade import run_once
from secure_env import validate_kis_credentials, validate_live_order_confirm, validate_telegram_if_enabled
from validated_inputs import OrderIntent


def main() -> int:
    load_dotenv(".env")
    arm_phrase = (os.getenv("LIVE_ARM_PHRASE") or "").strip()
    required_phrase = "START_LIVE"
    if arm_phrase != required_phrase:
        print("LIVE_START_BLOCKED: set LIVE_ARM_PHRASE=START_LIVE in .env to allow live run.")
        return 1

    test_symbol = (os.getenv("TEST_SYMBOL") or "005930").strip()
    test_qty = int((os.getenv("TEST_QTY") or "1").strip())

    try:
        OrderIntent(symbol=test_symbol, qty=test_qty)
    except Exception as exc:
        print(f"FAILED: invalid symbol/qty ({exc})")
        return 1

    try:
        validate_live_order_confirm()
        validate_telegram_if_enabled()
        
    except Exception as exc:
        print(f"FAILED: {exc}")
        return 1

    if os.getenv("SKIP_KIS_ENV_VALIDATION", "").strip().lower() not in {"1", "true", "yes"}:
        min_k = int(os.getenv("KIS_MIN_KEY_LEN", "8"))
        min_s = int(os.getenv("KIS_MIN_SECRET_LEN", "8"))
        try:
            validate_kis_credentials(min_key_len=min_k, min_secret_len=min_s)
        except Exception as exc:
            print(f"FAILED: env validation ({exc})")
            return 1

    return run_once(dry_run=False, test_symbol=test_symbol, test_qty=test_qty)


if __name__ == "__main__":
    sys.exit(main())
