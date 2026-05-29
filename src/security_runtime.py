"""
실행 시 보안·안정성 파라미터 (버전, HTTP, 서킷브레이커 등).
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

RULEBOOK_SECURITY_VERSION = "2026.05.14"


@dataclass(frozen=True)
class SecurityRuntime:
    rulebook_security_version: str
    http_timeout_sec: float
    max_http_retries: int
    circuit_fail_threshold: int
    circuit_cooldown_sec: int
    max_notional_krw_per_day: float
    log_level: str
    strict_env: bool


def _i(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    return default if not raw else int(float(raw))


def _f(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    return default if not raw else float(raw)


def get_security_runtime() -> SecurityRuntime:
    load_dotenv(".env")
    strict = (os.getenv("SECURE_STRICT") or "").strip().lower() in {"1", "true", "yes", "y"}
    return SecurityRuntime(
        rulebook_security_version=os.getenv("RULEBOOK_SECURITY_VERSION", RULEBOOK_SECURITY_VERSION),
        http_timeout_sec=_f("KIS_HTTP_TIMEOUT", 20.0),
        max_http_retries=_i("KIS_MAX_RETRIES", 3),
        circuit_fail_threshold=_i("KIS_CB_FAILURES", 5),
        circuit_cooldown_sec=_i("KIS_CB_COOLDOWN_SEC", 1800),
        max_notional_krw_per_day=_f("MAX_NOTIONAL_KRW_PER_DAY", 0.0),
        log_level=(os.getenv("LOG_LEVEL") or "WARNING").strip().upper(),
        strict_env=strict,
    )
