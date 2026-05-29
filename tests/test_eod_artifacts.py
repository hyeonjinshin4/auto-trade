"""eod_artifacts KST·빌드 조건."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from eod_artifacts import is_eod_build_window_kst, is_kr_equity_session_kst, needs_eod_build

KST = timezone(timedelta(hours=9))


def _kst(y: int, m: int, d: int, hh: int, mm: int) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=KST)


def test_session_kst() -> None:
    assert is_kr_equity_session_kst(_kst(2026, 5, 29, 10, 0))
    assert not is_kr_equity_session_kst(_kst(2026, 5, 29, 16, 0))
    assert not is_kr_equity_session_kst(_kst(2026, 5, 30, 10, 0))  # Saturday


def test_eod_window_kst() -> None:
    assert not is_eod_build_window_kst(_kst(2026, 5, 29, 15, 30))
    assert is_eod_build_window_kst(_kst(2026, 5, 29, 15, 35))
    assert is_eod_build_window_kst(_kst(2026, 5, 29, 20, 0))


def test_needs_build_outside_window(monkeypatch) -> None:
    monkeypatch.setenv("EOD_AUTO_BUILD", "true")
    monkeypatch.setenv("EOD_BUILD_DASHBOARD", "true")
    assert needs_eod_build(_kst(2026, 5, 29, 10, 0)) is False
