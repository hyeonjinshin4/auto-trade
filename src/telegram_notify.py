import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

_log = logging.getLogger(__name__)

_KST = timezone(timedelta(hours=9))

# (kind, symbol, KST날짜) 당일 동일 실패 알림 — 메모리 + 파일(재시작·다중 프로세스에도 유지)
_fail_tg_once_keys: set[str] = set()


def _to_bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def kst_today_ymd() -> str:
    return datetime.now(_KST).strftime("%Y%m%d")


def _fail_dedup_file_path() -> Path:
    raw = (os.getenv("TELEGRAM_FAIL_DEDUP_FILE") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path(__file__).resolve().parent.parent / "logs" / "telegram_fail_dedup.json"


def _fail_dedup_load_keys() -> set[str]:
    p = _fail_dedup_file_path()
    if not p.is_file():
        return set()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("keys"), list):
            return {str(x) for x in data["keys"] if isinstance(x, str)}
    except Exception as exc:
        _log.warning("telegram_fail_dedup read: %s", exc)
    return set()


def _fail_dedup_save_keys(keys: set[str]) -> None:
    """최대 800개, 오래된 키는 날짜 접미사 기준으로 정리."""
    p = _fail_dedup_file_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        _log.warning("telegram_fail_dedup mkdir: %s", exc)
        return
    today = kst_today_ymd()
    pruned: list[str] = []
    for k in sorted(keys):
        if not isinstance(k, str) or ":" not in k:
            continue
        suf = k.rsplit(":", 1)[-1]
        if len(suf) == 8 and suf.isdigit() and suf < today:
            continue
        pruned.append(k)
    pruned = pruned[-800:]
    tmp = p.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps({"keys": pruned}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
    except Exception as exc:
        _log.warning("telegram_fail_dedup write: %s", exc)


def _fail_dedup_all_keys() -> set[str]:
    return set(_fail_tg_once_keys) | _fail_dedup_load_keys()


def clear_fail_telegram_dedup(symbol: str, *kinds: str) -> None:
    """검증 통과·주문 성공 시 당일 중복 억제 상태 제거(이후 동일 실패면 다시 알림)."""
    sym = symbol.strip()
    day = kst_today_ymd()
    keys = kinds if kinds else ("buy_validate", "sell_order_fail", "buy_order_fail", "force_daily_buy")
    to_remove = {f"{k}:{sym}:{day}" for k in keys}
    changed = False
    for k in to_remove:
        if k in _fail_tg_once_keys:
            _fail_tg_once_keys.discard(k)
            changed = True
    disk = _fail_dedup_load_keys()
    new_disk = disk - to_remove
    if new_disk != disk:
        changed = True
    if changed:
        _fail_dedup_save_keys(new_disk)


def send_telegram_fail_once(kind: str, symbol: str, text: str) -> None:
    """
    동일 kind·종목·KST당일에는 최초 1회만 전송 (market_watch 반복 시 스팸 방지).
    `logs/telegram_fail_dedup.json` 에도 기록해 프로세스 재시작 후에도 중복 억제.
    TELEGRAM_FAIL_ALERT_DEDUP=false 이면 매번 전송.
    """
    load_dotenv(".env")
    if not _to_bool(os.getenv("TELEGRAM_ENABLED", "true")):
        return
    if not _to_bool(os.getenv("TELEGRAM_FAIL_ALERT_DEDUP", "true")):
        send_telegram(text)
        return
    sym = symbol.strip()
    key = f"{kind}:{sym}:{kst_today_ymd()}"
    merged = _fail_dedup_all_keys()
    if key in merged:
        _log.info("[TELEGRAM] 동일 실패 알림 생략 kind=%s symbol=%s (당일 이미 전송)", kind, sym)
        return
    send_telegram(text)
    _fail_tg_once_keys.add(key)
    merged.add(key)
    _fail_dedup_save_keys(merged)


def telegram_enabled() -> bool:
    load_dotenv(".env")
    if not _to_bool(os.getenv("TELEGRAM_ENABLED", "true")):
        return False
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    return bool(token and chat_id)


def send_telegram(text: str, *, disable_notification: bool = False) -> None:
    """
    텔레그램 Bot API로 메시지 전송. TELEGRAM_ENABLED=false 이거나 토큰/채팅ID 없으면 무시.
    4096자 초과 시 여러 메시지로 분할.
    """
    load_dotenv(".env")
    if not _to_bool(os.getenv("TELEGRAM_ENABLED", "true")):
        return
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat_id:
        return

    max_len = 4000
    chunks: list[str] = []
    rest = text
    while rest:
        chunks.append(rest[:max_len])
        rest = rest[max_len:]

    base = f"https://api.telegram.org/bot{token}/sendMessage"
    for i, chunk in enumerate(chunks):
        body: dict[str, Any] = {
            "chat_id": chat_id,
            "text": chunk if i == 0 else f"(계속 {i + 1}/{len(chunks)})\n{chunk}",
            "disable_notification": disable_notification,
        }
        response = requests.post(base, json=body, timeout=30)
        response.raise_for_status()
