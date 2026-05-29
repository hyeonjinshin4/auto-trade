# KIS Auto Trade Setup

한국투자증권 API로 인증/조회/주문을 연결하는 최소 실행 프로젝트입니다.

## 1) 설치

```bash
python3 -m pip install -r requirements.txt
```

## 2) 환경변수 작성

`.env`가 **없을 때만** 예시를 복사합니다 (`-n`: 이미 있으면 덮어쓰지 않음).

```bash
cp -n .env.example .env
```

이미 `.env`를 채워 두었다면 **`cp .env.example .env`를 다시 실행하지 마세요.** 매번 실행하면 내용이 예시 파일로 **전부 덮어써집니다.**

필수값:

- `APP_KEY`
- `APP_SECRET`
- `ACCOUNT_NO` (`12345678-01` 형태)
- `KIS_ENV`: **실전 매매는 `prod`**, 모의투자만 할 때 `vts`. 실전 앱키로 `vts` URL을 치면 오류(`EGW02007` 등)가 납니다.

추가값:

- `DRY_RUN` (`true` 권장)
- `TEST_SYMBOL` (기본 `005930`)
- `TEST_QTY` (기본 `1`)

## 3) 인증 확인

```bash
python3 src/kis_auth_check.py
```

## 4) 자동매매 한 번만(수동 한 사이클)

```bash
python3 src/auto_trade.py
```

- `DRY_RUN=true`: 실제 주문 미실행
- `DRY_RUN=false`: 조건 충족 시 주문 시도

## 4b) 1분 간격 자동매매 스킴 (권장 운영)

한 사이클(`run_trading_cycle`) 안에서 순서가 고정되어 있습니다.

1. **후보 종목 스캔** — `AUTO_SCAN_*` 또는 `AUTO_TRADE_SYMBOLS` (후보가 적으면 `AUTO_SCAN_MAX_PRICE_KRW`·시총 필터를 완화하거나 `AUTO_SCAN_MAX_SYMBOLS`·`AUTO_SCAN_POOL_TOP`을 키우세요.)
2. **매도 후 매수** — 보유 종목에 매도 시그널이 있으면 먼저 매도(`AUTO_RUN_SELLS`), 이후 엔진이 고른 1종을 검증·매수
3. **텔레그램 보고** — 실매매로 매수 주문이 나간 뒤, 주문 응답과 당일 체결 조회 결과를 전송 (`TELEGRAM_POST_BUY_REPORT=true`, 텔레그램 토큰·채팅 ID 필요)

`.env` 예시:

```env
TRADING_WATCH=true
TRADING_WATCH_INTERVAL_SEC=60
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
TELEGRAM_POST_BUY_REPORT=true
# DRY_RUN 인데 ‘엔진 PICK’만 텔레로 받으려면 (스팸 주의):
# TELEGRAM_NOTIFY_PICK_DRY_RUN=true
```

실행(프로젝트 루트에서):

```bash
python3 src/market_watch.py
```

- **평일 KST 09:00~15:30**에만 실제 사이클을 돌리고, 그 외에는 `skip (장외)`만 출력합니다 (AWS 서버가 UTC여도 KST로 판정).
- **KST 15:35 이후** `reports/dashboard_eod.html` · `reports/trade_export_YYYY-MM-DD.csv` 자동 생성 (`EOD_AUTO_BUILD=true`, 저널 갱신 시 재빌드).
- 종료: `Ctrl+C`
- 한국투자 **접근토큰은 1분에 1회** 제한이 있어, 매 사이클마다 새 토큰을 받지 않도록 프로젝트에 **토큰 캐시**(`.kis_token_cache.json`)가 있습니다.
- **API URL이 수시로 바뀌는 구조는 아닙니다.** 실전/모의 **호스트·`/oauth2/tokenP`** 등은 `kis_client.py`에 고정되어 있으며, 바뀌는 경우는 증권사 공지 수준입니다.

## 점수 기반 매매 (엔진 + TA 조건별 가점)

**매수:** `합산 = clamp(0..100, 엔진 + TA매수가점 − TA매도감점)`  
- TA **매수** 조건마다 독립 가점 (RSI +14 등, `ta_scoring.py`)  
- TA **매도** 조건이 뜨면 **매수와 같은 점수만큼 차감** (RSI 과매수 −14, 데드크로스 −16 등)  
- 매수 추세필터: 종가 ≥ 20일선일 때만 TA 매수 가점 합산 (아래면 조건은 로그에만 표시)  
- **tier:** `TRADING_SCORE_FULL` / `HALF`

**매도(청산):** 손절·익절·트레일 **또는** TA 매도 시그널 **주요 2개 이상 + 종가 ≤ 20일선** (`min_signals`, `confirm_trend`)  
- `TRADING_TA_SELL_SCORE_MIN=28` (감점 합 하한, 예: RSI+MACD 2개)

## AWS에서 돌릴 때 (대시보드·Mac 동기화)

1. EC2 `.env`에 `EOD_AUTO_BUILD=true` (기본값) 확인 후 `market_watch` 재시작.
2. 장 마감 후 로그에 `EOD artifacts OK: .../reports/dashboard_eod.html` 가 보이면 성공.
3. Mac에서 최신 파일 받기:

```bash
scp user@YOUR_EC2:~/자동매매/reports/dashboard_eod.html ./reports/
scp user@YOUR_EC2:~/자동매매/reports/trade_export_*.csv ./reports/
scp user@YOUR_EC2:~/자동매매/logs/trade_journal.csv ./logs/
```

`market_watch`가 15:35 전에 종료되면 크론 백업:

```cron
35 15 * * 1-5 TZ=Asia/Seoul /home/ubuntu/자동매매/scripts/cron_eod_kr.sh >> /home/ubuntu/자동매매/logs/cron_eod.log 2>&1
```

선택: `EOD_S3_BUCKET`·`EOD_S3_PREFIX` 설정 시 `aws s3 cp`로 HTML·CSV 업로드. `EOD_TELEGRAM_NOTIFY=true`면 생성 경로를 텔레그램으로 알림.

## 프로젝트 구조 (핵심만)

| 경로 | 역할 |
|------|------|
| `src/market_watch.py` | 주기 실행 진입점 → `trade_runner.run_trading_cycle` |
| `src/trade_runner.py` | 한 사이클 오케스트레이션 (스캔·매도·매수·텔레그램) |
| `src/trade_ops.py` | 매매 보조 통합 (포지션 JSON, 기준가/주문유형, breadth, 매도·매수 후보) |
| `src/kis_client.py` | KIS API (토큰·조회·주문) |
| `src/trading_rules/` | 규칙북·엔진·사이징·청산 |
| `src/regime_engine.py`, `factors/`, `adaptive/`, `state_machine/` | 선택 기능 (`USE_ADAPTIVE_REGIME`, `USE_RS_RANKING` 등 env로 켬) |

## 5) "바로 시작" 실행 준비

실거래 즉시 실행용 명령:

```bash
python3 src/start_live.py
```

실수 방지 장치로 `.env`에 아래가 있어야 실행됩니다.

```env
LIVE_ARM_PHRASE=START_LIVE
TEST_SYMBOL=005930
TEST_QTY=1
```

사용 흐름:

1. 평소: `DRY_RUN=true` 상태로 점검
2. 시작 직전: `LIVE_ARM_PHRASE=START_LIVE` 설정
3. 실행: `python3 src/start_live.py`
