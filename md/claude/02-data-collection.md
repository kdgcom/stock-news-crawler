# 데이터 수집 전략

## 1. 수집 대상 데이터 분류

| 분류 | 데이터 유형 | 활용 목적 |
|------|------------|-----------|
| **뉴스** | 기업별 뉴스, 시장 뉴스, 속보 | 감성 분석, 이벤트 감지 |
| **시세** | 실시간 주가, 거래량, 호가 | 기술적 분석, 진입/청산 타이밍 |
| **공시** | DART 공시, SEC Filing | 기업 이벤트 감지 |
| **재무** | 재무제표, 실적 발표 | 기본적 분석, 밸류에이션 |
| **대안 데이터** | SNS 여론, 검색 트렌드 | 시장 심리 보조 지표 |

---

## 2. 국내 뉴스 수집

### 2.1 데이터 소스

| 소스 | 수집 방법 | 특징 |
|------|-----------|------|
| **네이버 금융 뉴스** | HTML 크롤링 | 종목별 뉴스 집계, 실시간 속보 |
| **한국경제** | HTML 크롤링 / RSS | 시장 분석 기사 풍부 |
| **매일경제** | HTML 크롤링 / RSS | 기업 뉴스 커버리지 넓음 |
| **연합인포맥스** | API (유료) | 금융 전문 뉴스, 속보성 높음 |
| **DART 전자공시** | OpenAPI | 기업 공시 데이터 (무료) |

### 2.2 네이버 금융 뉴스 크롤링 전략

네이버 금융은 종목별 뉴스를 체계적으로 분류하여 제공하며, 국내 주식 뉴스의 핵심 집계 소스이다.

**수집 대상 URL 패턴:**
```
# 종목별 뉴스
https://finance.naver.com/item/news.nhn?code={종목코드}

# 실시간 속보
https://finance.naver.com/news/news_list.nhn?mode=LSS2D&section_id=101&section_id2=258

# 시장 주요 뉴스
https://finance.naver.com/news/mainnews.nhn
```

**수집 흐름:**
```
1. 관심 종목 목록에서 종목코드 추출
2. 각 종목의 뉴스 페이지 순회
3. 뉴스 제목, URL, 발행일시, 출처 추출
4. 개별 뉴스 링크 접속하여 본문 수집
5. 중복 검사 후 MongoDB 저장
```

**크롤링 시 주의사항:**
- `robots.txt` 준수
- 요청 간격 최소 1~2초 유지 (서버 부하 방지)
- User-Agent를 적절히 설정
- IP 차단 대비 재시도 로직 및 지수 백오프 적용
- 네이버 서비스 약관 확인 필요

### 2.3 DART 공시 수집

DART OpenAPI를 통해 기업 공시를 실시간으로 수집할 수 있다.

**활용 API:**
```
# 공시 검색
https://opendart.fss.or.kr/api/list.json?crtfc_key={API키}&corp_code={기업코드}

# 기업 개황
https://opendart.fss.or.kr/api/company.json?crtfc_key={API키}&corp_code={기업코드}
```

**수집할 공시 유형:**
- 주요사항보고서 (유상증자, 합병, 분할 등)
- 실적 공시 (매출, 영업이익 등)
- 지분 변동 (대량보유, 임원 지분 변동)
- 자사주 취득/처분

---

## 3. 미국 뉴스 수집

### 3.1 데이터 소스

| 소스 | 수집 방법 | 특징 | 비용 |
|------|-----------|------|------|
| **Alpaca News API** | REST API | 실시간 주식/크립토 뉴스, 무료 티어 있음 | 무료~유료 |
| **MarketAux** | REST API | 80+ 시장, 5,000+ 소스, 감성 태깅 | 무료 티어 있음 |
| **Benzinga** | REST/FTP/TCP | 저지연, 시장 뉴스 전문 | 유료 |
| **SEC EDGAR** | REST API | 공시(10-K, 10-Q, 8-K 등) | 무료 |
| **Yahoo Finance** | yfinance 라이브러리 | 주가 + 뉴스 통합 | 무료 |
| **Google News RSS** | RSS 피드 | 범용 뉴스 집계 | 무료 |

### 3.2 권장 조합

**비용 효율적 조합 (초기 단계):**
```
뉴스: Alpaca News API (무료 티어) + MarketAux (무료 티어)
공시: SEC EDGAR (무료)
주가: Yahoo Finance / yfinance (무료)
```

**고품질 조합 (고도화 단계):**
```
뉴스: Benzinga API (유료, 저지연)
공시: SEC EDGAR + Polygon.io (유료)
주가: Alpaca Market Data (유료) 또는 Polygon.io
```

### 3.3 Alpaca News API 활용 예시

```python
import requests

ALPACA_API_KEY = "your_api_key"
ALPACA_SECRET_KEY = "your_secret_key"
BASE_URL = "https://data.alpaca.markets/v1beta1/news"

headers = {
    "APCA-API-KEY-ID": ALPACA_API_KEY,
    "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
}

params = {
    "symbols": "AAPL,TSLA,NVDA",
    "limit": 50,
    "sort": "desc",
}

response = requests.get(BASE_URL, headers=headers, params=params)
news_data = response.json()
```

### 3.4 SEC EDGAR 공시 수집

```python
# SEC EDGAR API - 8-K (주요 이벤트) 조회 예시
SEC_BASE_URL = "https://efts.sec.gov/LATEST/search-index"

params = {
    "q": "AAPL",
    "dateRange": "custom",
    "startdt": "2025-01-01",
    "enddt": "2025-12-31",
    "forms": "8-K",
}
```

---

## 4. 실시간 시세 수집

### 4.1 국내 주식 시세 - 한국투자증권 API

한국투자증권(KIS)의 Open API는 REST + WebSocket 기반으로 실시간 시세를 제공한다.

**REST API (조회형):**
```python
# 현재가 조회
GET /uapi/domestic-stock/v1/quotations/inquire-price
Header: {
    "authorization": "Bearer {access_token}",
    "appkey": "{app_key}",
    "appsecret": "{app_secret}",
    "tr_id": "FHKST01010100"
}
Query: { "FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": "005930" }
```

**WebSocket (실시간):**
```python
# 실시간 체결가 수신
import websockets
import json

async def connect_kis_websocket():
    uri = "ws://ops.koreainvestment.com:21000"
    async with websockets.connect(uri) as ws:
        # 실시간 체결가 등록
        subscribe_msg = {
            "header": {"approval_key": "{approval_key}", "tr_type": "1"},
            "body": {"input": {"tr_id": "H0STCNT0", "tr_key": "005930"}}
        }
        await ws.send(json.dumps(subscribe_msg))

        async for message in ws:
            process_tick(message)
```

**유의사항 (2026년 기준):**
- WebSocket 무한루프 호출 시 자동 차단 정책 시행 중
- REST API 초당 호출 제한 준수 필요 (초당 20회 이내 권장)
- 모의투자 서버에서 충분히 테스트 후 실전 전환

### 4.2 미국 주식 시세 - Alpaca API

```python
# Alpaca 실시간 시세 (WebSocket)
from alpaca.data.live import StockDataStream

stream = StockDataStream("api_key", "secret_key")

async def on_bar(bar):
    print(f"{bar.symbol}: {bar.close} (volume: {bar.volume})")

stream.subscribe_bars(on_bar, "AAPL", "TSLA", "NVDA")
stream.run()
```

**대안: python-kis를 통한 미국 주식 시세**

한국투자증권 API는 해외 주식도 지원하므로, 하나의 증권사 API로 국내/미국 모두 커버할 수 있다.

```python
# python-kis 라이브러리를 통한 해외 주식 조회
from pykis import KisClient

client = KisClient(appkey="...", appsecret="...", account="...")
price = client.overseas_stock_price("AAPL", market="NAS")
```

---

## 5. 데이터 저장 전략

### 5.1 MongoDB (비정형 데이터)

기존 프로젝트의 MongoDB를 확장하여 뉴스, 공시, 분석 결과를 저장한다.

**컬렉션 설계:**

```javascript
// news_articles (기존 확장)
{
    _id: ObjectId,
    title: "삼성전자 반도체 실적 호전",
    content: "...",
    company_name: "삼성전자",
    stock_code: "005930",
    market: "KRX",              // KRX | NASDAQ | NYSE
    source: "네이버금융",
    url: "https://...",
    published_date: ISODate,
    crawled_date: ISODate,

    // 분석 결과 (신규)
    sentiment: {
        score: 0.82,            // -1.0 ~ 1.0
        label: "positive",      // positive | negative | neutral
        confidence: 0.91,
        analyzed_by: "claude-3-sonnet",
        analyzed_at: ISODate
    },
    entities: [                 // 언급된 기업/인물
        { name: "삼성전자", type: "company", ticker: "005930" },
        { name: "SK하이닉스", type: "company", ticker: "000660" }
    ],
    impact_keywords: ["실적", "반도체", "호전"],
    related_tickers: ["005930", "000660"]
}

// trading_signals (신규)
{
    _id: ObjectId,
    ticker: "005930",
    market: "KRX",
    signal_type: "BUY",         // BUY | SELL | HOLD
    confidence: 0.78,
    reasons: [
        { type: "sentiment", detail: "최근 24시간 뉴스 감성 +0.72" },
        { type: "technical", detail: "RSI 35 (과매도 구간)" },
        { type: "fundamental", detail: "PER 12.3 (업종 평균 대비 저평가)" }
    ],
    source_articles: [ObjectId, ObjectId],
    created_at: ISODate,
    executed: false,
    execution_result: null
}

// trade_history (신규)
{
    _id: ObjectId,
    ticker: "005930",
    market: "KRX",
    action: "BUY",
    quantity: 10,
    price: 72500,
    total_amount: 725000,
    signal_id: ObjectId,
    broker: "KIS",
    order_id: "...",
    status: "filled",           // pending | filled | cancelled | failed
    executed_at: ISODate,
    pnl: null                   // 청산 시 손익 기록
}
```

### 5.2 TimescaleDB (시계열 데이터)

주가 시세 데이터는 시계열 특성이 강하므로 TimescaleDB를 사용한다.

```sql
-- 분봉 데이터 테이블
CREATE TABLE stock_ohlcv (
    time        TIMESTAMPTZ NOT NULL,
    ticker      TEXT NOT NULL,
    market      TEXT NOT NULL,     -- KRX, NASDAQ, NYSE
    open        DECIMAL(15,4),
    high        DECIMAL(15,4),
    low         DECIMAL(15,4),
    close       DECIMAL(15,4),
    volume      BIGINT,
    vwap        DECIMAL(15,4)      -- 거래량 가중 평균가
);

-- 하이퍼테이블로 변환
SELECT create_hypertable('stock_ohlcv', 'time');

-- 종목+시간 인덱스
CREATE INDEX ON stock_ohlcv (ticker, time DESC);

-- 기술적 지표 (연속 집계)
CREATE MATERIALIZED VIEW stock_indicators
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('5 minutes', time) AS bucket,
    ticker,
    market,
    first(open, time) AS open,
    max(high) AS high,
    min(low) AS low,
    last(close, time) AS close,
    sum(volume) AS volume
FROM stock_ohlcv
GROUP BY bucket, ticker, market;
```

---

## 6. 크롤링 스케줄링

### 6.1 국내 시장 스케줄

```python
# 장 운영 시간: 09:00 ~ 15:30 KST
SCHEDULE_KR = {
    "pre_market": {
        "time": "08:00",
        "tasks": ["전일 공시 분석", "해외 시장 영향 분석", "관심 종목 뉴스 수집"]
    },
    "market_open": {
        "time": "09:00",
        "tasks": ["실시간 시세 WebSocket 연결", "뉴스 속보 모니터링 시작"]
    },
    "intraday": {
        "interval": "1min",
        "tasks": ["뉴스 크롤링", "시세 기록", "시그널 평가"]
    },
    "market_close": {
        "time": "15:30",
        "tasks": ["WebSocket 해제", "일일 리포트 생성"]
    },
    "after_hours": {
        "time": "16:00",
        "tasks": ["장후 공시 수집", "다음 날 전략 수립"]
    }
}
```

### 6.2 미국 시장 스케줄

```python
# 장 운영 시간: 09:30 ~ 16:00 ET (한국 시간 23:30 ~ 06:00)
SCHEDULE_US = {
    "pre_market": {
        "time": "22:00 KST",    # ET 08:00
        "tasks": ["프리마켓 뉴스 수집", "실적 발표 확인"]
    },
    "market_open": {
        "time": "23:30 KST",    # ET 09:30
        "tasks": ["실시간 시세 연결", "뉴스 모니터링"]
    },
    "intraday": {
        "interval": "1min",
        "tasks": ["뉴스 크롤링", "시세 기록", "시그널 평가"]
    },
    "market_close": {
        "time": "06:00 KST",    # ET 16:00
        "tasks": ["일일 리포트", "다음 거래일 전략"]
    }
}
```

---

## 7. 데이터 품질 관리

### 7.1 중복 제거
- 뉴스 URL 기반 중복 체크 (MongoDB unique index)
- 유사도 기반 중복 뉴스 탐지 (제목 유사도 > 0.85이면 동일 뉴스로 판단)

### 7.2 데이터 유효성 검증
- 시세 데이터: 전일 종가 대비 ±30% 이상 변동 시 이상치로 표시
- 뉴스 데이터: 본문 길이 최소 100자 이상, 빈 콘텐츠 필터링
- 타임스탬프 정합성 체크

### 7.3 장애 복구
- 크롤링 실패 시 지수 백오프로 재시도 (최대 5회)
- WebSocket 연결 끊김 시 자동 재연결 + 누락 데이터 REST로 보충
- 수집 지연 감지 시 알림 발송

---

## 8. 법적 고려사항

### 8.1 웹 크롤링 관련
- 각 웹사이트의 `robots.txt` 및 이용약관 확인 필수
- 과도한 요청으로 인한 서비스 방해 금지
- 가능한 경우 공식 API 사용 우선 (크롤링 대신)
- 수집한 데이터의 상업적 재배포 금지

### 8.2 증권사 API 관련
- API 이용약관 준수
- 호출 빈도 제한 (Rate Limit) 준수
- 모의투자 충분한 테스트 후 실전 전환
- 개인 계정 기반으로만 사용 (타인 계정 대리 거래 금지)

### 8.3 개인정보 보호
- API 키, 계좌 정보 등은 `.env` 파일로 관리, 저장소에 커밋하지 않음
- `.gitignore`에 민감 파일 패턴 등록 확인
