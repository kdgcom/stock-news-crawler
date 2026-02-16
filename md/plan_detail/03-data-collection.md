# 03. 데이터 수집 파이프라인

> Phase 1 - Track B | 의존: Track A (인프라) | 소요: Week 2~5

## 수집 대상 및 주기

### 장중 수집 (5분 주기)

| 소스 | 시장 | 방법 | 주기 | Phase |
|------|------|------|------|-------|
| 네이버 금융 뉴스 | KR | HTML 크롤링 | 5분 | 1 |
| DART 전자공시 | KR | OpenAPI | 10분 | 1 |
| KIS 시세 | KR | REST API | 5분 | 1 |
| Alpaca News | US | REST API | 5분 | 1 |
| SEC EDGAR | US | REST API | 30분 | 1 |
| yfinance 시세 | US | 라이브러리 | 5분 | 1 |

### 장전 수집 (1일 1회)

| 소스 | 시간 (KST) | 설명 |
|------|-----------|------|
| 전일 US 마감 데이터 | 07:00 | 지수, 주요 종목 종가, 뉴스 |
| KR 조간 뉴스 | 07:30 | 과거 12시간 뉴스 일괄 수집 |
| DART 전일 공시 | 07:30 | 장 마감 후 공시 |
| US 프리마켓 뉴스 | 22:00 | KR 마감 후 ~ US 장전 뉴스 |

## 수집기 아키텍처

```
Cloud Scheduler (cron)
    │
    ▼
Cloud Run (수집기)
    │
    ├── BaseCollector          ← 공통: 재시도, 정규화, 에러 핸들링
    │     ├── KRNewsCollector      (네이버금융, DART)
    │     ├── USNewsCollector      (Alpaca, SEC)
    │     ├── KRPriceCollector     (KIS API)
    │     └── USPriceCollector     (yfinance)
    │
    ├── Normalizer             ← 표준 스키마 변환
    │
    └── Output
          ├── → MongoDB        (뉴스 raw)
          ├── → GCS → BigQuery (시세 5분봉, 배치 로드)
          └── → Redis          (최근 캐시)
```

## 공통 규칙

```python
# BaseCollector
class BaseCollector:
    MAX_RETRIES = 5
    BACKOFF_BASE = 2  # 지수 백오프 (2, 4, 8, 16, 32초)

    def collect(self):
        for attempt in range(self.MAX_RETRIES):
            try:
                raw = self.fetch()
                normalized = self.normalize(raw)
                self.store(normalized)
                return normalized
            except Exception as e:
                wait = self.BACKOFF_BASE ** attempt
                log.warning(f"Retry {attempt+1}/{self.MAX_RETRIES}, wait {wait}s: {e}")
                time.sleep(wait)
        self.alert_failure()  # 5회 실패 → 알림 발송
```

**핵심 규칙:**
- `robots.txt` / 이용약관 준수
- 지수 백오프 재시도 (최대 5회)
- source timestamp + ingest timestamp 동시 저장
- 수집기 단일 실패가 파이프라인 전체로 전파되지 않도록 격리

## 뉴스 수집 상세

### 네이버 금융 (KR)

```python
# 수집 흐름
# 1. 종목별 뉴스 목록 페이지 크롤링
# 2. 최근 수집 이후 신규 기사만 필터
# 3. 기사 본문 크롤링
# 4. 정규화 → MongoDB 저장

def collect_naver_news(symbol: str, since: datetime):
    url = f"https://finance.naver.com/item/news.naver?code={symbol}"
    # ... HTML 파싱
    for article in articles:
        event_id = hash_event_id(
            source="naver_finance",
            url=article.url,
            published_at=article.published_at_utc
        )
        # upsert by event_id (멱등)
```

### DART 공시 (KR)

```python
# DART OpenAPI: https://opendart.fss.or.kr
# 무료, API 키 필요, 일 1만건 제한
# 수집 주기: 10분 (공시 빈도 낮음)
```

### Alpaca News (US)

```python
# Alpaca News API: 무료 티어
# GET /v1beta1/news?symbols=AAPL&start=...
# 수집 주기: 5분
```

## 시세 수집 상세

### 5분봉 수집 + 파생 필드 계산

```python
def collect_price(symbol: str, market: str):
    # 1분봉 5개 수집 (최근 5분)
    bars_1m = fetch_1m_bars(symbol, count=5)

    # 5분봉 OHLCV 집계
    bar_5m = {
        "ts_event": bars_1m[0]["timestamp"],
        "symbol": symbol,
        "market": market,
        "open": bars_1m[0]["open"],
        "high": max(b["high"] for b in bars_1m),
        "low": min(b["low"] for b in bars_1m),
        "close": bars_1m[-1]["close"],
        "volume": sum(b["volume"] for b in bars_1m),
        "vwap": weighted_avg(bars_1m),
        # 파생 필드
        "high_minute": argmax([b["high"] for b in bars_1m]),
        "low_minute": argmin([b["low"] for b in bars_1m]),
        "intra_stddev": stdev([b["close"] for b in bars_1m]),
        "volume_skew": volume_skew(bars_1m),
        "bar_trend": trend_direction(bars_1m),
    }

    # 저장
    write_to_gcs(bar_5m)           # → BigQuery 배치 로드
    cache_to_redis(bar_5m)          # → 최근 200바 캐시
```

## 저장 경로

| 데이터 | 즉시 저장 | 배치 저장 | 캐시 |
|--------|----------|----------|------|
| 뉴스 원문 | MongoDB `raw_news_events` | — | — |
| 뉴스 분석 | MongoDB `enriched_news_events` | — | Redis (30분 TTL) |
| 시세 5분봉 | — | GCS → BigQuery | Redis (최근 200바) |
| 뉴스 메트릭 | — | BigQuery (시간/일별) | — |

## 완료 기준

- [ ] KR 뉴스 수집: 네이버금융 24시간 무중단
- [ ] KR 시세 수집: KIS API 5분 주기 정상
- [ ] US 뉴스 수집: Alpaca News 24시간 무중단
- [ ] US 시세 수집: yfinance 5분 주기 정상
- [ ] 동일 event_id 100회 입력 시 저장 1건 (멱등성)
- [ ] BigQuery 배치 로드 5분 주기 정상
- [ ] Redis 캐시 최근 200바 유지 확인
