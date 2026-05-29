"""
민감 환경변수 검증. 로그 문자열에서 토큰·키 노출을 줄이기 위한 마스킹.
"""
from __future__ import annotations

import os
import re


def redact_secrets(text: str) -> str:
    """환경에 등록된 키/시크릿이 문자열에 포함되면 치환."""
    out = text
    for key in ("APP_KEY", "APP_SECRET", "TELEGRAM_BOT_TOKEN"):
        val = (os.getenv(key) or "").strip()
        if len(val) >= 8 and val in out:
            out = out.replace(val, "[REDACTED]")
    out = re.sub(r"Bearer\s+\S+", "Bearer [REDACTED]", out, flags=re.I)
    out = re.sub(r"(access_token)\s*[:=]\s*[^\s,}\"']+", r"\1=[REDACTED]", out, flags=re.I)
    return out


def _nonempty(name: str) -> str:
    v = (os.getenv(name) or "").strip()
    if not v:
        raise RuntimeError(f"필수 환경변수 누락: {name}")
    return v


def validate_kis_credentials(*, min_key_len: int = 8, min_secret_len: int = 8) -> None:
    """KIS OpenAPI 최소 요건. 길이만 검사(형식은 증권사 정책에 따름)."""
    key = _nonempty("APP_KEY")
    secret = _nonempty("APP_SECRET")
    acct = _nonempty("ACCOUNT_NO")
    if len(key) < min_key_len:
        raise ValueError("APP_KEY 형식이 비정상적으로 짧습니다.")
    if len(secret) < min_secret_len:
        raise ValueError("APP_SECRET 형식이 비정상적으로 짧습니다.")
    if len(acct) < 8:
        raise ValueError("ACCOUNT_NO 형식이 비정상적으로 짧습니다.")


def validate_kis_token_only(*, min_key_len: int = 8, min_secret_len: int = 8) -> None:
    """토큰 발급만 할 때 (계좌번호 불필요)."""
    key = _nonempty("APP_KEY")
    secret = _nonempty("APP_SECRET")
    if len(key) < min_key_len:
        raise ValueError("APP_KEY 형식이 비정상적으로 짧습니다.")
    if len(secret) < min_secret_len:
        raise ValueError("APP_SECRET 형식이 비정상적으로 짧습니다.")


def validate_telegram_if_enabled() -> None:
    if os.getenv("TELEGRAM_ENABLED", "true").strip().lower() in {"0", "false", "no"}:
        return
    tid = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    cid = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    if not tid or not cid:
        raise RuntimeError("TELEGRAM_ENABLED 인데 TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID 누락")


def validate_live_order_confirm() -> None:
    """실주문 경로에서 이중 확인 (dry_run=False 시)."""
    need = (os.getenv("CONFIRM_LIVE") or "").strip()
    expected = "I_ACCEPT_ORDER_RISK"
    if need != expected:
        raise RuntimeError(
            f"실주문 허용: .env에 CONFIRM_LIVE={expected} 를 설정하세요 (오타 방지 이중 확인)."
        )
