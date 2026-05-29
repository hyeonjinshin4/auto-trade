from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Any, Optional

import requests
from dotenv import load_dotenv

from kis_token_cache import read_cached_token, write_token_cache
from safe_logging import get_safe_logger
from secure_env import validate_kis_credentials
from security_runtime import get_security_runtime

_log = get_safe_logger(__name__)

_guard: Any = None


def _get_call_guard() -> Any:
    global _guard
    if _guard is None:
        from kis_guard import KISCallGuard

        sr = get_security_runtime()
        _guard = KISCallGuard(
            max_per_minute=int(os.getenv("KIS_MAX_PER_MINUTE", "60")),
            fail_threshold=sr.circuit_fail_threshold,
            cooldown_sec=sr.circuit_cooldown_sec,
        )
    return _guard


class KISClient:
    def __init__(self) -> None:
        load_dotenv(".env")
        if os.getenv("SKIP_KIS_ENV_VALIDATION", "").strip().lower() not in {"1", "true", "yes"}:
            min_k = int(os.getenv("KIS_MIN_KEY_LEN", "8"))
            min_s = int(os.getenv("KIS_MIN_SECRET_LEN", "8"))
            validate_kis_credentials(min_key_len=min_k, min_secret_len=min_s)
        sr = get_security_runtime()
        self._timeout = sr.http_timeout_sec
        self._use_guard = os.getenv("USE_KIS_REQUEST_GUARD", "").strip().lower() in {"1", "true", "yes"}
        self.app_key = (os.getenv("APP_KEY") or "").strip()
        self.app_secret = (os.getenv("APP_SECRET") or "").strip()
        self.account_no = (os.getenv("ACCOUNT_NO") or "").strip()
        self.product_code = (os.getenv("PRODUCT_CODE") or "01").strip()
        self.kis_env = (os.getenv("KIS_ENV") or "prod").strip().lower()
        self.base_url = (
            "https://openapi.koreainvestment.com:9443"
            if self.kis_env == "prod"
            else "https://openapivts.koreainvestment.com:29443"
        )
        self.access_token = self._issue_access_token()
        self._cano, self._acnt_prdt_cd = self._split_account()

    def _http(self, fn: Callable[[], requests.Response]) -> requests.Response:
        if self._use_guard:
            return _get_call_guard().run(fn)
        return fn()

    def _split_account(self) -> tuple[str, str]:
        raw = self.account_no.strip()
        if "-" in raw:
            a, b = raw.split("-", 1)
            return a.strip(), b.strip()
        if len(raw) >= 10:
            return raw[:8], raw[8:10]
        return raw, self.product_code

    def _issue_access_token(self) -> str:
        cached = read_cached_token(
            app_key=self.app_key, app_secret=self.app_secret, kis_env=self.kis_env
        )
        if cached:
            return cached

        url = f"{self.base_url}/oauth2/tokenP"
        payload = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
        }

        def do_req() -> requests.Response:
            return requests.post(
                url,
                json=payload,
                headers={"content-type": "application/json; charset=UTF-8"},
                timeout=self._timeout,
            )

        response = self._http(do_req)
        response.raise_for_status()
        data = response.json()
        token = data.get("access_token")
        if not token:
            raise RuntimeError("Token missing in response")
        exp = str(data.get("access_token_token_expired") or "")
        write_token_cache(
            app_key=self.app_key,
            app_secret=self.app_secret,
            kis_env=self.kis_env,
            access_token=token,
            access_token_token_expired=exp,
        )
        return token

    def _headers(self, tr_id: str, *, tr_cont: Optional[str] = None) -> dict[str, str]:
        h: dict[str, str] = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self.access_token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
            "custtype": "P",
        }
        if tr_cont is not None:
            h["tr_cont"] = tr_cont
        return h

    @staticmethod
    def _kis_json_body(response: requests.Response) -> Optional[dict[str, Any]]:
        """응답이 JSON 객체이면 dict로 파싱 (실패 시 None)."""
        try:
            if not (response.text or "").strip():
                return None
            data = response.json()
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def _raise_balance_api_error_if_any(self, response: requests.Response) -> None:
        """
        HTTP 4xx/5xx 이어도 본문에 rt_cd/msg_cd가 오는 경우가 있음(예: EGW02007 + HTTP 500).
        raise_for_status()보다 원인 메시지를 우선 노출.
        """
        if response.ok:
            return
        body = self._kis_json_body(response)
        if not body:
            return
        code = str(body.get("msg_cd") or "").strip()
        msg1 = str(body.get("msg1") or "").strip()
        if code == "EGW02007":
            if self.kis_env != "prod":
                raise RuntimeError(
                    "KIS 모의투자(vts): APP_KEY/APP_SECRET이 모의투자용이 아닙니다 (msg_cd=EGW02007). "
                    "한국투자증권 개발자포털에서 [모의투자] 앱을 새로 등록해 키를 발급받고 .env에 넣거나, "
                    "실전 키·실계좌만 쓸 경우 KIS_ENV=prod 로 바꾸세요."
                ) from None
            raise RuntimeError(f"KIS 잔고조회: {code} — {msg1}") from None
        if code == "EGW02006":
            raise RuntimeError(f"KIS 잔고조회 (msg_cd={code}): {msg1}") from None
        if msg1 or code:
            raise RuntimeError(
                f"KIS 잔고조회 실패 (HTTP {response.status_code}, msg_cd={code}): {msg1}"
            ) from None

    def _raise_order_api_error_if_any(self, response: requests.Response, *, side: str) -> None:
        """주문 API HTTP 오류 시 KIS msg_cd/msg1 우선 노출."""
        if response.ok:
            return
        body = self._kis_json_body(response)
        if not body:
            return
        code = str(body.get("msg_cd") or "").strip()
        msg1 = str(body.get("msg1") or "").strip()
        rt = str(body.get("rt_cd") or "").strip()
        label = "매수" if side == "buy" else "매도"
        if code == "EGW02007":
            hint = (
                "모의투자 키·KIS_ENV=vts 확인."
                if self.kis_env != "prod"
                else "실전 키·KIS_ENV=prod 확인."
            )
            raise RuntimeError(f"KIS {label}주문: {code} — {msg1} ({hint})") from None
        if code == "IGW00002":
            raise RuntimeError(
                f"KIS {label}주문: {code} — {msg1} "
                f"(요청 CANO={self._cano} ACNT_PRDT_CD={self._acnt_prdt_cd}). "
                ".env 의 ACCOUNT_NO 를 OpenAPI 앱에 등록한 실계좌(예: 12345678-01)로 맞추고, "
                "변경 후 .kis_token_cache.json 삭제 뒤 market_watch 재시작."
            ) from None
        if msg1 or code or rt:
            raise RuntimeError(
                f"KIS {label}주문 실패 (HTTP {response.status_code}, rt_cd={rt}, msg_cd={code}): {msg1}"
            ) from None

    def _order_tr_id(self, side: str) -> str:
        """
        국내 현금주문 TR_ID.
        공식 examples_llm 기준: 실전 TTTC0011U(매도)/TTTC0012U(매수).
        KIS_ORDER_LEGACY_TR_ID=true 시 구버전 0801/0802 사용.
        """
        legacy = (os.getenv("KIS_ORDER_LEGACY_TR_ID") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "y",
        }
        if side == "buy":
            env_override = (os.getenv("KIS_ORDER_TR_ID_BUY") or "").strip()
            if env_override:
                return env_override
            if legacy:
                return "TTTC0802U" if self.kis_env == "prod" else "VTTC0802U"
            return "TTTC0012U" if self.kis_env == "prod" else "VTTC0012U"
        env_override = (os.getenv("KIS_ORDER_TR_ID_SELL") or "").strip()
        if env_override:
            return env_override
        if legacy:
            return "TTTC0801U" if self.kis_env == "prod" else "VTTC0801U"
        return "TTTC0011U" if self.kis_env == "prod" else "VTTC0011U"

    def _order_cash_body(
        self,
        *,
        symbol: str,
        qty: int,
        side: str,
        order_dvsn: str,
        price: int,
    ) -> dict[str, str]:
        sym = symbol.strip().zfill(6)
        body: dict[str, str] = {
            "CANO": self._cano,
            "ACNT_PRDT_CD": self._acnt_prdt_cd,
            "PDNO": sym,
            "ORD_DVSN": order_dvsn,
            "ORD_QTY": str(int(qty)),
            "ORD_UNPR": str(int(price)),
            "EXCG_ID_DVSN_CD": (os.getenv("KIS_ORDER_EXCG_ID_DVSN_CD") or "KRX").strip() or "KRX",
            "CNDT_PRIC": (os.getenv("KIS_ORDER_CNDT_PRIC") or "").strip(),
        }
        if side == "sell":
            body["SLL_TYPE"] = (os.getenv("KIS_ORDER_SLL_TYPE") or "01").strip() or "01"
        return body

    def _balance_query_params(self) -> dict[str, str]:
        """
        국내 잔고조회(8434R) 쿼리. 한투 예시·문서는 대체로 PRCS_DVSN=00 과 맞춤.
        (기존 01 조합에서 모의서버가 HTTP 500을 내는 사례가 있어 00 기본값.)
        """
        ofl = (os.getenv("KIS_BALANCE_OFL_YN") or "").strip()
        if not ofl:
            ofl = ""
        return {
            "CANO": self._cano,
            "ACNT_PRDT_CD": self._acnt_prdt_cd,
            "AFHR_FLPR_YN": (os.getenv("KIS_BALANCE_AFHR_FLPR_YN") or "N").strip(),
            "OFL_YN": ofl,
            "INQR_DVSN": (os.getenv("KIS_BALANCE_INQR_DVSN") or "02").strip(),
            "UNPR_DVSN": (os.getenv("KIS_BALANCE_UNPR_DVSN") or "01").strip(),
            "FUND_STTL_ICLD_YN": (os.getenv("KIS_BALANCE_FUND_STTL_ICLD_YN") or "N").strip(),
            "FNCG_AMT_AUTO_RDPT_YN": (os.getenv("KIS_BALANCE_FNCG_AMT_AUTO_RDPT_YN") or "N").strip(),
            "PRCS_DVSN": (os.getenv("KIS_BALANCE_PRCS_DVSN") or "00").strip(),
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }

    @staticmethod
    def _log_balance_http_error(response: requests.Response, *, tr_id: str) -> None:
        """HTTP 오류 시 본문 일부만 로그(원인 파악용)."""
        snippet = ""
        try:
            txt = response.text or ""
            snippet = txt[:800]
            if len(txt) > 800:
                snippet += "...(truncated)"
        except Exception:
            snippet = "(no body)"
        _log.error(
            "inquire-balance HTTP %s | tr_id=%s | body_snippet=%s",
            response.status_code,
            tr_id,
            snippet,
        )

    def inquire_balance(self) -> dict[str, Any]:
        """
        국내주식 잔고 조회.
        """
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
        params = self._balance_query_params()
        tr_id = "TTTC8434R" if self.kis_env == "prod" else "VTTC8434R"
        retries = max(0, min(int((os.getenv("KIS_BALANCE_HTTP_RETRIES") or "2").strip() or "2"), 5))
        delay = max(0.2, float((os.getenv("KIS_BALANCE_HTTP_RETRY_SEC") or "1.2").strip() or "1.2"))

        last_response: Optional[requests.Response] = None
        for attempt in range(retries + 1):
            def do_req() -> requests.Response:
                return requests.get(url, headers=self._headers(tr_id), params=params, timeout=self._timeout)

            response = self._http(do_req)
            last_response = response
            if response.ok:
                break
            self._log_balance_http_error(response, tr_id=tr_id)
            err_body = self._kis_json_body(response)
            if err_body and str(err_body.get("msg_cd") or "").strip() in {"EGW02007", "EGW02006"}:
                break
            if response.status_code < 500:
                break
            if attempt < retries:
                _log.warning(
                    "inquire-balance %s, retry %s/%s after %.1fs",
                    response.status_code,
                    attempt + 1,
                    retries,
                    delay,
                )
                time.sleep(delay)
        assert last_response is not None
        if not last_response.ok:
            self._raise_balance_api_error_if_any(last_response)
        last_response.raise_for_status()
        return last_response.json()

    def inquire_daily_ccld(
        self,
        inqr_strt_dt: str,
        inqr_end_dt: str,
        *,
        ccld_dvsn: str = "01",
        odno: str = "",
        sll_buy_dvsn_cd: str = "00",
    ) -> list[dict[str, Any]]:
        """
        국내주식 일별주문체결조회 (output1 누적). ccld_dvsn: 00 전체, 01 체결, 02 미체결.
        """
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-daily-ccld"
        tr_id = "TTTC8001R" if self.kis_env == "prod" else "VTTC8001R"
        all_rows: list[dict[str, Any]] = []
        ctx_fk, ctx_nk = "", ""
        tr_cont_send: Optional[str] = None

        while True:
            headers = self._headers(tr_id, tr_cont=tr_cont_send)
            params: dict[str, str] = {
                "CANO": self._cano,
                "ACNT_PRDT_CD": self._acnt_prdt_cd,
                "INQR_STRT_DT": inqr_strt_dt,
                "INQR_END_DT": inqr_end_dt,
                "SLL_BUY_DVSN_CD": sll_buy_dvsn_cd,
                "INQR_DVSN": "01",
                "PDNO": "",
                "CCLD_DVSN": ccld_dvsn,
                "ORD_GNO_BRNO": "",
                "ODNO": odno,
                "INQR_DVSN_3": "00",
                "INQR_DVSN_1": "",
                "CTX_AREA_FK100": ctx_fk,
                "CTX_AREA_NK100": ctx_nk,
            }

            def do_req() -> requests.Response:
                return requests.get(url, headers=headers, params=params, timeout=self._timeout)

            response = self._http(do_req)
            response.raise_for_status()
            data = response.json()
            chunk = data.get("output1")
            if chunk is None:
                rows: list[dict[str, Any]] = []
            elif isinstance(chunk, list):
                rows = chunk
            else:
                rows = [chunk]
            all_rows.extend(rows)

            tr_cont = (response.headers.get("tr_cont") or "D").strip().upper()
            if tr_cont in ("D", "E"):
                break
            ctx_fk = str(data.get("ctx_area_fk100") or "")
            ctx_nk = str(data.get("ctx_area_nk100") or "")
            tr_cont_send = "N"

        return all_rows

    def inquire_overseas_present_balance(self) -> dict[str, Any]:
        """
        해외주식 체결기준 현재잔고 (미국 등 보유·평가).
        """
        url = f"{self.base_url}/uapi/overseas-stock/v1/trading/inquire-present-balance"
        tr_id = "CTRP6504R" if self.kis_env == "prod" else "VTRP6504R"
        params = {
            "CANO": self._cano,
            "ACNT_PRDT_CD": self._acnt_prdt_cd,
            "WCRC_FRCR_DVSN_CD": "02",
            "NATN_CD": "840",
            "TR_MKET_CD": "00",
            "INQR_DVSN_CD": "00",
        }

        def do_req() -> requests.Response:
            return requests.get(url, headers=self._headers(tr_id), params=params, timeout=self._timeout)

        response = self._http(do_req)
        response.raise_for_status()
        return response.json()

    def inquire_price(self, symbol: str, *, market_div: str = "J") -> dict[str, Any]:
        """국내주식 현재가 (주식현재가 시세)."""
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-price"
        tr_id = "FHKST01010100"
        params = {
            "FID_COND_MRKT_DIV_CODE": market_div,
            "FID_INPUT_ISCD": symbol.strip(),
        }

        def do_req() -> requests.Response:
            return requests.get(url, headers=self._headers(tr_id), params=params, timeout=self._timeout)

        response = self._http(do_req)
        response.raise_for_status()
        data = response.json()
        out = data.get("output")
        return out if isinstance(out, dict) else {}

    def _place_order_cash(
        self,
        *,
        symbol: str,
        qty: int,
        side: str,
        order_dvsn: str,
        price: int,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-cash"
        body = self._order_cash_body(
            symbol=symbol,
            qty=qty,
            side=side,
            order_dvsn=order_dvsn,
            price=price,
        )
        tr_id = self._order_tr_id(side)

        def do_req() -> requests.Response:
            return requests.post(url, headers=self._headers(tr_id), json=body, timeout=self._timeout)

        response = self._http(do_req)
        if not response.ok:
            snippet = (response.text or "")[:600]
            _log.error(
                "order-cash HTTP %s side=%s tr_id=%s body=%s resp=%s",
                response.status_code,
                side,
                tr_id,
                body,
                snippet,
            )
            self._raise_order_api_error_if_any(response, side=side)
        response.raise_for_status()
        data = response.json()
        rt = str(data.get("rt_cd") or "")
        if rt not in {"0", "00"}:
            msg1 = str(data.get("msg1") or "")
            code = str(data.get("msg_cd") or "")
            raise RuntimeError(
                f"KIS {'매수' if side == 'buy' else '매도'}주문 거절 rt_cd={rt} msg_cd={code}: {msg1}"
            )
        return data

    def place_order_cash_buy(
        self,
        symbol: str,
        qty: int,
        *,
        price: int = 0,
        order_dvsn: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        국내주식 현금 매수.
        order_dvsn 미지정 시 price=0 → 시장가(01), 아니면 지정가(00).
        """
        if order_dvsn is None:
            order_dvsn = "01" if price == 0 else "00"
        return self._place_order_cash(
            symbol=symbol, qty=qty, side="buy", order_dvsn=order_dvsn, price=price
        )

    def place_order_cash_sell(
        self,
        symbol: str,
        qty: int,
        *,
        price: int = 0,
        order_dvsn: Optional[str] = None,
    ) -> dict[str, Any]:
        """국내주식 현금 매도."""
        if order_dvsn is None:
            order_dvsn = "01" if price == 0 else "00"
        return self._place_order_cash(
            symbol=symbol, qty=qty, side="sell", order_dvsn=order_dvsn, price=price
        )
