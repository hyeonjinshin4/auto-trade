"""
KIS OAuth 토큰을 짧게 재사용해 '1분당 1회' 발급 제한(EGW00133) 완화.
캐시는 프로젝트 루트 `.kis_token_cache.json` (gitignore).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 프로젝트 루트 (…/자동매매/.kis_token_cache.json)
_CACHE_PATH = Path(__file__).resolve().parent.parent / ".kis_token_cache.json"
_SKEW = timedelta(seconds=90)


def _fingerprint(app_key: str, app_secret: str, kis_env: str) -> str:
    raw = f"{app_key}|{app_secret}|{kis_env}".encode()
    return hashlib.sha256(raw).hexdigest()


def _parse_expires(s: str) -> datetime | None:
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=timezone(timedelta(hours=9)))
        except ValueError:
            continue
    return None


def read_cached_token(*, app_key: str, app_secret: str, kis_env: str) -> str | None:
    fp = _fingerprint(app_key, app_secret, kis_env)
    if not _CACHE_PATH.is_file():
        return None
    try:
        data = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if data.get("fingerprint") != fp:
        return None
    token = (data.get("access_token") or "").strip()
    exp = _parse_expires(str(data.get("access_token_token_expired") or ""))
    if not token or exp is None:
        return None
    if datetime.now(timezone.utc) >= exp - _SKEW:
        return None
    return token


def write_token_cache(
    *,
    app_key: str,
    app_secret: str,
    kis_env: str,
    access_token: str,
    access_token_token_expired: str,
) -> None:
    payload = {
        "fingerprint": _fingerprint(app_key, app_secret, kis_env),
        "access_token": access_token,
        "access_token_token_expired": access_token_token_expired,
    }
    try:
        _CACHE_PATH.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
