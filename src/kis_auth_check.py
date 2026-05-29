import os
import sys

import requests
from dotenv import load_dotenv

from kis_token_cache import read_cached_token, write_token_cache
from secure_env import validate_kis_token_only


def main() -> int:
    load_dotenv(".env")

    if os.getenv("SKIP_KIS_ENV_VALIDATION", "").strip().lower() not in {"1", "true", "yes"}:
        try:
            min_k = int(os.getenv("KIS_MIN_KEY_LEN", "8"))
            min_s = int(os.getenv("KIS_MIN_SECRET_LEN", "8"))
            validate_kis_token_only(min_key_len=min_k, min_secret_len=min_s)
        except Exception as exc:
            print(f"FAILED: {exc}")
            return 1

    app_key = (os.getenv("APP_KEY") or "").strip()
    app_secret = (os.getenv("APP_SECRET") or "").strip()
    kis_env = (os.getenv("KIS_ENV") or "prod").strip().lower()

    if not app_key or not app_secret:
        print("FAILED: APP_KEY or APP_SECRET is missing in .env")
        return 1

    if kis_env not in {"prod", "vts"}:
        print("FAILED: KIS_ENV must be 'prod' or 'vts'")
        return 1

    base_url = (
        "https://openapi.koreainvestment.com:9443"
        if kis_env == "prod"
        else "https://openapivts.koreainvestment.com:29443"
    )
    cached = read_cached_token(app_key=app_key, app_secret=app_secret, kis_env=kis_env)
    if cached:
        print("SUCCESS: KIS token (cached, 재발급 생략)")
        print(f"KIS_ENV={kis_env}")
        print(f"TOKEN_LENGTH={len(cached)}")
        print("HINT: 새로 발급받으려면 .kis_token_cache.json 을 지우고 1분 뒤 다시 실행하세요.")
        return 0

    url = f"{base_url}/oauth2/tokenP"

    payload = {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "appsecret": app_secret,
    }

    try:
        response = requests.post(
            url,
            json=payload,
            headers={"content-type": "application/json; charset=UTF-8"},
            timeout=20,
        )
    except requests.RequestException as exc:
        print(f"FAILED: network error ({exc})")
        return 1

    if response.status_code != 200:
        print(f"FAILED: HTTP {response.status_code}")
        try:
            body = response.json()
            print(body)
            if body.get("error_code") == "EGW00133":
                print(
                    "HINT: 한투는 접근토큰 발급이 1분에 1회입니다. "
                    "방금 다른 스크립트(auto_trade 등)가 발급했다면 60초 후 재시도하거나, "
                    "프로젝트 루트의 .kis_token_cache.json 이 있으면 kis_auth_check 가 캐시를 씁니다."
                )
        except ValueError:
            print(response.text)
        return 1

    data = response.json()
    token = data.get("access_token")
    if not token:
        print("FAILED: no access_token in response")
        print(data)
        return 1

    write_token_cache(
        app_key=app_key,
        app_secret=app_secret,
        kis_env=kis_env,
        access_token=token,
        access_token_token_expired=str(data.get("access_token_token_expired") or ""),
    )
    print("SUCCESS: KIS token issued")
    print(f"KIS_ENV={kis_env}")
    print(f"TOKEN_LENGTH={len(token)}")
    print(f"EXPIRES_AT={data.get('access_token_token_expired', 'N/A')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
