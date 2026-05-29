"""
잔고·체결·저널 포맷 (텔레그램 메시지용).
"""
from __future__ import annotations

import csv
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_KST = timezone(timedelta(hours=9))


def _num(v: Any) -> str:
    if v is None:
        return "-"
    s = str(v).strip()
    return s if s else "-"


def append_trade_journal(
    path: str,
    *,
    symbol: str,
    qty: int,
    odno: str,
    reason: str,
    order_rt_cd: str,
    msg: str,
) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    new_file = not p.exists()
    reason_clean = reason.replace("\n", " ").replace("\r", " ")
    msg_clean = msg.replace("\n", " ").replace("\r", " ")[:500]
    with p.open("a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["ts", "symbol", "qty", "odno", "reason", "rt_cd", "msg"])
        w.writerow(
            [
                datetime.now().isoformat(timespec="seconds"),
                symbol,
                qty,
                odno,
                reason_clean,
                order_rt_cd,
                msg_clean,
            ]
        )


def _parse_float(x: Any) -> float:
    try:
        return float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _parse_int(x: Any) -> int:
    try:
        return int(float(str(x).replace(",", "")))
    except (TypeError, ValueError):
        return 0


def mask_account_display(account_no: str) -> str:
    """예: 50123456-01 → 50****56-01 (앞2·뒤2만 노출)."""
    raw = (account_no or "").strip()
    if not raw:
        return "-"
    if "-" in raw:
        cano, prod = raw.split("-", 1)
    elif len(raw) >= 10:
        cano, prod = raw[:8], raw[8:10]
    else:
        return raw
    cano = cano.strip()
    prod = prod.strip()
    if len(cano) >= 4:
        masked_cano = f"{cano[:2]}****{cano[-2:]}"
    else:
        masked_cano = cano
    return f"{masked_cano}-{prod}" if prod else masked_cano


def _format_krw_int(price: float) -> str:
    if price <= 0:
        return "-"
    return f"{int(round(price)):,}원"


def _format_ord_time(row: dict[str, Any] | None) -> str:
    if row:
        raw = str(row.get("ORD_TMD") or row.get("CCLD_TMD") or "").strip()
        digits = "".join(c for c in raw if c.isdigit())
        if len(digits) >= 4:
            return f"{digits[:2]}:{digits[2:4]}"
    return datetime.now(_KST).strftime("%H:%M")


def _side_from_ccld_row(row: dict[str, Any]) -> str | None:
    code = str(row.get("SLL_BUY_DVSN_CD") or row.get("sll_buy_dvsn_cd") or "").strip()
    if code == "02":
        return "buy"
    if code == "01":
        return "sell"
    return None


def _pick_ccld_row(fills: list[dict[str, Any]], odno: str) -> dict[str, Any] | None:
    if not fills:
        return None
    target = (odno or "").strip()
    if target:
        matched = [
            r
            for r in fills
            if str(r.get("ODNO") or r.get("odno") or "").strip() == target
        ]
        if matched:
            return matched[-1]
    return fills[-1]


def _row_val(row: dict[str, Any], *keys: str) -> Any:
    """KIS 응답 키 대소문자·별칭 허용."""
    if not row:
        return None
    norm = {str(k).lower(): v for k, v in row.items()}
    for k in keys:
        v = norm.get(k.lower())
        if v is not None and str(v).strip() != "":
            return v
    return None


def row_confirmed_fill(row: dict[str, Any] | None, *, odno: str) -> tuple[int, int, float] | None:
    """
    KIS 체결 row에서 실제 체결만 인정 (주문번호 일치 + 체결수량>0 + 체결단가>0).
    hint/주문수량으로 채우지 않음.
    """
    if not row or not str(odno).strip():
        return None
    row_odno = str(_row_val(row, "ODNO", "odno") or "").strip()
    if row_odno != str(odno).strip():
        return None

    ccld_qty = _parse_int(
        _row_val(
            row,
            "TOT_CCLD_QTY",
            "tot_ccld_qty",
            "CCLD_QTY",
            "ccld_qty",
            "THDT_BUY_CCLD_QTY1",
            "THDT_SLL_CCLD_QTY1",
        )
    )
    if ccld_qty <= 0:
        return None

    avg = _parse_float(
        _row_val(
            row,
            "AVG_PRVS",
            "avg_prvs",
            "CCLD_UNPR",
            "ccld_unpr",
        )
    )
    if avg <= 0:
        amt = _parse_float(_row_val(row, "CCLD_AMT", "ccld_amt", "TOT_CCLD_AMT", "tot_ccld_amt"))
        if ccld_qty > 0 and amt > 0:
            avg = amt / ccld_qty
    if avg <= 0:
        return None

    ord_qty = _parse_int(
        _row_val(
            row,
            "ORD_QTY",
            "ord_qty",
            "TOT_ORD_QTY",
            "tot_ord_qty",
        )
    )
    if ord_qty <= 0:
        ord_qty = ccld_qty
    return ccld_qty, ord_qty, avg


def poll_order_fill(
    client: Any,
    odno: str,
    *,
    wait_sec: float = 3.0,
    poll_n: int = 4,
) -> tuple[int, int, float] | None:
    """당일 체결 조회를 반복해 ODNO 일치 체결을 찾으면 (체결수량, 주문수량, 단가) 반환."""
    target = str(odno).strip()
    if not target:
        return None
    today = datetime.now(_KST).strftime("%Y%m%d")
    for attempt in range(max(1, poll_n)):
        if attempt > 0:
            time.sleep(max(1.0, wait_sec))
        else:
            time.sleep(min(2.0, wait_sec))
        try:
            fills = client.inquire_daily_ccld(today, today, ccld_dvsn="01", odno=target)
        except Exception:
            continue
        row = _pick_ccld_row(fills, target)
        confirmed = row_confirmed_fill(row, odno=target)
        if confirmed:
            return confirmed
    return None


def _parse_ccld_qty_price(
    row: dict[str, Any] | None,
    *,
    order_qty: int | None,
    fill_price_hint: float | None,
    allow_hints: bool = False,
) -> tuple[int, int, float]:
    """(체결수량, 주문수량, 체결단가). allow_hints=False면 API 체결만 (텔레그램·체결확인용)."""
    if not row:
        if not allow_hints:
            return 0, 0, 0.0
        oq = max(0, int(order_qty or 0))
        fp = float(fill_price_hint or 0.0)
        return oq, oq, fp

    ord_qty = _parse_int(
        _row_val(
            row,
            "ORD_QTY",
            "ord_qty",
            "TOT_ORD_QTY",
            "tot_ord_qty",
        )
    )
    ccld_qty = _parse_int(
        _row_val(
            row,
            "TOT_CCLD_QTY",
            "tot_ccld_qty",
            "CCLD_QTY",
            "ccld_qty",
            "THDT_BUY_CCLD_QTY1",
            "THDT_SLL_CCLD_QTY1",
        )
    )
    if ccld_qty <= 0 and allow_hints:
        ccld_qty = ord_qty

    avg = _parse_float(
        _row_val(
            row,
            "AVG_PRVS",
            "avg_prvs",
            "CCLD_UNPR",
            "ccld_unpr",
            "ORD_UNPR",
            "ord_unpr",
        )
    )
    if avg <= 0:
        amt = _parse_float(_row_val(row, "CCLD_AMT", "ccld_amt", "TOT_CCLD_AMT", "tot_ccld_amt"))
        if ccld_qty > 0 and amt > 0:
            avg = amt / ccld_qty
    if allow_hints and avg <= 0 and fill_price_hint and float(fill_price_hint) > 0:
        avg = float(fill_price_hint)

    if allow_hints:
        if ord_qty <= 0 and order_qty and order_qty > 0:
            ord_qty = int(order_qty)
        if ccld_qty <= 0 and order_qty and order_qty > 0:
            ccld_qty = int(order_qty)
    if ord_qty <= 0 and ccld_qty > 0:
        ord_qty = ccld_qty

    return ccld_qty, ord_qty, avg


def format_kis_fill_telegram(
    fills: list[dict[str, Any]],
    *,
    odno: str = "",
    side: str | None = None,
    symbol: str = "",
    stock_name: str = "",
    order_qty: int | None = None,
    fill_price_hint: float | None = None,
    trade_reason: str = "",
    account_no: str = "",
    account_name: str = "",
) -> str:
    """
    한국투자증권 체결안내 스타일 텔레그램 본문.
  [한국투자증권 체결안내]10:26
  *계좌번호:46****60-01
  ...
    """
    row = _pick_ccld_row(fills, odno)
    confirmed = row_confirmed_fill(row, odno=odno or "")
    if not confirmed:
        return (
            "[체결 확인 실패]\n"
            f"주문번호 {odno or '-'} — KIS 체결 API에 일치 체결이 없습니다.\n"
            "HTS에서 미체결/체결 여부를 확인하세요."
        )

    ccld_qty, ord_qty, avg = confirmed
    eff_side = side or (_side_from_ccld_row(row) if row else None) or "buy"
    trade_label = "현금매수체결" if eff_side == "buy" else "현금매도체결"

    sym = (symbol or "").strip()
    if row and not sym:
        sym = str(row.get("PDNO") or "").strip()
    sym = sym.zfill(6) if sym else ""

    name = (stock_name or "").strip()
    if row and not name:
        name = str(_row_val(row, "PRDT_NAME", "prdt_name", "prdt_abrv_name") or "").strip()
    if name and sym:
        name_line = f"{name}({sym})"
    elif sym:
        name_line = sym
    else:
        name_line = name or "-"

    odno_out = str(_row_val(row, "ODNO", "odno") or odno or "").strip() if row else (odno or "").strip()

    acct_raw = (account_no or os.getenv("ACCOUNT_NO") or "").strip()
    acct_name = (account_name or os.getenv("TELEGRAM_ACCOUNT_NAME") or "").strip() or "-"
    hm = _format_ord_time(row)

    lines = [
        f"[한국투자증권 체결안내]{hm}",
        "",
        f"*계좌번호:{mask_account_display(acct_raw)}",
        f"*계좌명:{acct_name}",
        f"*매매구분:{trade_label}",
        f"*종목명:{name_line}",
        f"*체결수량:{ccld_qty}주",
        f"*체결단가:{_format_krw_int(avg)}",
        "",
        f"*주문수량:{ord_qty}주",
        f"*총체결수량:{ccld_qty}주",
        f"*주문번호:{odno_out or '-'}",
    ]
    reason = (trade_reason or "").strip().replace("\r\n", "\n")
    if reason:
        if len(reason) > 600:
            reason = reason[:597] + "..."
        lines.extend(["", "*매매근거:", reason])
    return "\n".join(lines)


def format_ccld_rows(rows: list[dict[str, Any]], *, title: str, max_rows: int = 30) -> str:
    if not rows:
        return f"{title}\n(체결/주문 내역 없음)"
    lines = [title, f"건수: {len(rows)}"]
    keys_priority = (
        "ORD_DT",
        "ORD_TMD",
        "ODNO",
        "PDNO",
        "PRDT_NAME",
        "SLL_BUY_DVSN_CD",
        "ORD_QTY",
        "TOT_CCLD_QTY",
        "CCLD_QTY",
        "CCLD_AMT",
        "TOT_CCLD_AMT",
        "ORD_UNPR",
        "AVG_PRVS",
        "CCLD_DVSN",
    )
    for i, row in enumerate(rows[:max_rows]):
        parts: list[str] = []
        for k in keys_priority:
            if k in row and str(row[k]).strip():
                parts.append(f"{k}={row[k]}")
        if not parts:
            parts = [f"{k}={v}" for k, v in sorted(row.items())[:12]]
        lines.append(f"[{i + 1}] " + ", ".join(parts))
    if len(rows) > max_rows:
        lines.append(f"... 외 {len(rows) - max_rows}건 생략")
    return "\n".join(lines)


def format_domestic_balance_summary(data: dict[str, Any], *, base_capital_krw: str) -> str:
    lines = ["[국내주식 잔고 요약]"]
    o2 = data.get("output2")
    if isinstance(o2, list) and o2:
        s = o2[0]
        if isinstance(s, dict):
            lines.append(f"총평가금액(tot_evlu_amt): {_num(s.get('tot_evlu_amt'))}")
            lines.append(f"순자산(nass_amt): {_num(s.get('nass_amt'))}")
            lines.append(f"매입금액합계(pchs_amt_smtl_amt): {_num(s.get('pchs_amt_smtl_amt'))}")
            lines.append(f"평가금액합계(evlu_amt_smtl_amt): {_num(s.get('evlu_amt_smtl_amt'))}")
            lines.append(f"평가손익합계(evlu_pfls_smtl_amt): {_num(s.get('evlu_pfls_smtl_amt'))}")
            nass = s.get("nass_amt")
            if base_capital_krw and nass not in (None, ""):
                try:
                    base = float(str(base_capital_krw).replace(",", ""))
                    nav = float(str(nass).replace(",", ""))
                    if base > 0:
                        pct = (nav - base) / base * 100.0
                        lines.append(f"기준자본 대비 수익률(추정): {pct:.2f}% (기준: {base:,.0f}원)")
                except ValueError:
                    lines.append("기준자본 대비 수익률: 계산 불가(BASE_CAPITAL_KRW 확인)")
    else:
        lines.append("(output2 없음)")
    return "\n".join(lines)


def format_overseas_balance(data: dict[str, Any]) -> str:
    lines = ["[해외주식 체결기준 잔고 (NATN_CD=840 미국)]"]
    rt = data.get("rt_cd")
    msg = data.get("msg1") or data.get("msg_cd")
    lines.append(f"rt_cd={_num(rt)}, msg={_num(msg)}")

    for label, key in (
        ("output1(종목)", "output1"),
        ("output2", "output2"),
        ("output3", "output3"),
    ):
        block = data.get(key)
        if block is None:
            continue
        if isinstance(block, dict):
            lines.append(f"\n--- {label} ---")
            for k, v in list(block.items())[:40]:
                lines.append(f"  {k}: {v}")
        elif isinstance(block, list) and block:
            lines.append(f"\n--- {label} ({len(block)}건) ---")
            for i, item in enumerate(block[:25]):
                if isinstance(item, dict):
                    short = ", ".join(f"{k}={v}" for k, v in list(item.items())[:14])
                    lines.append(f"  [{i + 1}] {short}")
                else:
                    lines.append(f"  [{i + 1}] {item}")
            if len(block) > 25:
                lines.append(f"  ... 외 {len(block) - 25}건")

    return "\n".join(lines)


def order_output_odno(result: dict[str, Any]) -> str:
    out = result.get("output")
    if isinstance(out, dict):
        v = out.get("ODNO") or out.get("odno")
        return str(v or "").strip()
    return ""
