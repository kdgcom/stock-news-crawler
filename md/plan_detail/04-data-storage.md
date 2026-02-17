# 04. 데이터 저장 전략

> Phase 1 - Track C | 의존: Track A (BigQuery/MongoDB 준비) | 소요: Week 2~4

## 저장소 역할 분담

```
BigQuery (분석/시계열)     MongoDB (뉴스/이벤트)     Redis (실시간)
─────────────────────    ────────────────────     ───────────────
market_5m_bars           raw_news_events          price_cache:{symbol}
market_1d_bars           enriched_news_events     sentiment:{symbol}
news_sentiment_hourly    (3개월 후 GCS 아카이브)     position:{symbol}
news_sentiment_daily                              stream:events
decision_logs                                     universe:tier1
positions_daily          Cloud Storage (아카이브)   config:*
stock_universe           news_archive/*.jsonl.gz
```

## BigQuery 스키마

### 시세 5분봉

```sql
CREATE TABLE stock_trading.market_5m_bars (
    ts_event      TIMESTAMP NOT NULL,
    symbol        STRING NOT NULL,
    market        STRING NOT NULL,
    open          NUMERIC,
    high          NUMERIC,
    low           NUMERIC,
    close         NUMERIC,
    volume        INT64,
    vwap          NUMERIC,
    spread_pct    FLOAT64,
    -- 파생 필드 (1분봉에서 계산)
    high_minute   INT64,
    low_minute    INT64,
    intra_stddev  FLOAT64,
    volume_skew   FLOAT64,
    bar_trend     INT64
)
PARTITION BY DATE(ts_event)
CLUSTER BY market, symbol;
```

### 일봉 (Scheduled Query로 자동 집계)

```sql
CREATE TABLE stock_trading.market_1d_bars (
    trade_date  DATE NOT NULL,
    symbol      STRING NOT NULL,
    market      STRING NOT NULL,
    open        NUMERIC,
    high        NUMERIC,
    low         NUMERIC,
    close       NUMERIC,
    volume      INT64,
    vwap        NUMERIC
)
PARTITION BY trade_date
CLUSTER BY market, symbol;

-- Scheduled Query: 매일 KR 16:00, US 07:00 (KST) 실행
-- 당일 5분봉 → 일봉 집계
```

### 뉴스 감성 시계열

```sql
CREATE TABLE stock_trading.news_sentiment_hourly (
    ts_bucket           TIMESTAMP NOT NULL,
    symbol              STRING NOT NULL,
    market              STRING NOT NULL,
    article_count       INT64,
    avg_sentiment       FLOAT64,
    max_sentiment       FLOAT64,
    min_sentiment       FLOAT64,
    weighted_sentiment  FLOAT64,
    avg_novelty         FLOAT64,
    dominant_event_type STRING
)
PARTITION BY DATE(ts_bucket)
CLUSTER BY market, symbol;

CREATE TABLE stock_trading.news_sentiment_daily (
    trade_date          DATE NOT NULL,
    symbol              STRING NOT NULL,
    market              STRING NOT NULL,
    article_count       INT64,
    avg_sentiment       FLOAT64,
    sentiment_trend     FLOAT64,       -- 전일 대비 변화
    dominant_event_type STRING
)
PARTITION BY trade_date
CLUSTER BY market, symbol;
```

### 의사결정 로그

```sql
CREATE TABLE stock_trading.decision_logs (
    decision_id       STRING NOT NULL,
    ts_utc            TIMESTAMP NOT NULL,
    symbol            STRING NOT NULL,
    market            STRING NOT NULL,
    decision          STRING,           -- BUY / SELL / HOLD
    score             FLOAT64,
    input_features_hash STRING,
    model_version     STRING,
    reason_codes      ARRAY<STRING>,
    reasons           JSON,
    risk_check        JSON,
    order_result      STRING
)
PARTITION BY DATE(ts_utc)
CLUSTER BY market, symbol;
```

### 포지션 스냅샷

```sql
CREATE TABLE stock_trading.positions_daily (
    snapshot_date  DATE NOT NULL,
    symbol         STRING NOT NULL,
    market         STRING NOT NULL,
    quantity       INT64,
    avg_cost       NUMERIC,
    current_price  NUMERIC,
    unrealized_pnl NUMERIC,
    realized_pnl   NUMERIC,
    weight_pct     FLOAT64
)
PARTITION BY snapshot_date;
```

### 종목 유니버스

```sql
CREATE TABLE stock_trading.stock_universe (
    symbol          STRING NOT NULL,
    market          STRING NOT NULL,
    name            STRING,
    sector          STRING,
    tier            INT64,
    tier_changed_at TIMESTAMP,
    promote_reason  STRING,
    market_cap_rank INT64,
    avg_volume_20d  INT64,
    is_excluded     BOOL,
    updated_at      TIMESTAMP
);
```

## MongoDB 스키마

### raw_news_events

```javascript
{
    event_id: "hash(source+url+published_at)",  // unique index
    market: "KR",
    symbol: "005930",
    headline: "삼성전자 실적 호전",
    body: "...",                                // 전문
    language: "ko",
    source_name: "네이버금융",
    source_type: "news",                        // news | disclosure | sns
    published_at_utc: ISODate,
    ingested_at_utc: ISODate,
    url: "https://..."
}
// Index: { event_id: 1 } (unique)
// Index: { market: 1, symbol: 1, published_at_utc: -1 }
// TTL Index: { ingested_at_utc: 1 }, expireAfterSeconds: 90일 (자동 삭제)
```

### enriched_news_events

```javascript
{
    event_id: "hash...",                        // raw와 동일 키
    event_type: "earnings",
    sentiment_score: 0.72,
    confidence: 0.85,
    impact_horizon: "short_term",
    novelty_score: 0.9,
    reliability_score: 0.95,
    cluster_id: "cluster_abc",
    entities: [{ name: "삼성전자", type: "company", ticker: "005930" }],
    topic_tags: ["반도체", "실적"],
    affected_symbols: ["005930", "000660"],
    summary: "삼성전자 4Q 영업이익 12조...",     // 2~3문장 요약
    analyzed_by: "rule_v1",
    analyzed_at_utc: ISODate
}
// Index: { event_id: 1 } (unique)
// Index: { affected_symbols: 1, analyzed_at_utc: -1 }
// TTL 없음 (영구 보존)
```

## 저장 주기 상세

### 장중 (5분마다)

```
매 5분:
  1. 시세 수집 → JSONL 파일 → GCS 업로드
  2. GCS → BigQuery 배치 로드 (무료)
  3. 동시에 Redis에 최근 시세 캐시
  4. 뉴스 수집 → MongoDB raw 저장
  5. 뉴스 분석 → MongoDB enriched 저장
  6. 감성 점수 → Redis 캐시 (TTL 30분)
```

### 장 마감 후 (일 1회)

```
KR 16:00 / US 07:00 (KST):
  1. BigQuery Scheduled Query: 5분봉 → 일봉 집계
  2. BigQuery Scheduled Query: 뉴스 감성 일별 집계
  3. Redis 포지션 → BigQuery positions_daily 스냅샷
  4. 일일 PnL 계산 → BigQuery
  5. Tier 3 스크리닝 → universe 테이블 업데이트
  6. 일일 리포트 생성 → Telegram 발송
```

### 주간 (일요일)

```
  1. 주간 성과 요약 리포트 생성
  2. 리스크 지표 리뷰
  3. 유니버스 재검토
```

### 월간 (매월 1일)

```
  1. MongoDB raw_news TTL에 의해 90일 이상 자동 삭제
     (삭제 전 GCS에 아카이브되어 있어야 함)
  2. BigQuery 5분봉 12개월 초과분 삭제 (수동 또는 스크립트)
  3. GCP 비용 점검
  4. 스토리지 용량 점검
```

### 아카이브 프로세스 (주 1회)

```python
# 3개월 이상 raw 뉴스 → GCS 압축 아카이브
def archive_old_news():
    cutoff = datetime.utcnow() - timedelta(days=90)
    old_docs = mongodb.raw_news_events.find(
        {"ingested_at_utc": {"$lt": cutoff}, "archived": {"$ne": True}}
    )

    # JSONL 형식으로 GCS에 압축 저장
    filename = f"news_archive/{cutoff.strftime('%Y%m')}.jsonl.gz"
    upload_to_gcs(old_docs, filename, compress=True)

    # 아카이브 플래그 (TTL Index가 자동 삭제 처리)
    mongodb.raw_news_events.update_many(
        {"ingested_at_utc": {"$lt": cutoff}},
        {"$set": {"archived": True}}
    )
```

## 보존 정책 요약

| 데이터 | 저장소 | Hot 보존 | 아카이브 | 영구 |
|--------|--------|---------|---------|------|
| 시세 5분봉 | BigQuery | 12개월 | — | 삭제 |
| 시세 일봉 | BigQuery | — | — | **영구** |
| 뉴스 raw | MongoDB | 3개월 | GCS 압축 5년 | — |
| 뉴스 enriched | MongoDB | — | — | **영구** |
| 뉴스 감성 시간별 | BigQuery | 12개월 | — | 삭제 |
| 뉴스 감성 일별 | BigQuery | — | — | **영구** |
| 의사결정 로그 | BigQuery | — | — | **영구** |
| 포지션 스냅샷 | BigQuery | — | — | **영구** |

## 완료 기준

- [ ] BigQuery 테이블 6종 생성 완료
- [ ] MongoDB 컬렉션 2종 + 인덱스 생성 완료
- [ ] GCS → BigQuery 배치 로드 테스트 성공
- [ ] Redis 캐시 읽기/쓰기 테스트 성공
- [ ] Scheduled Query 3종 등록 (일봉, 감성 시간별, 감성 일별)
- [ ] 아카이브 스크립트 동작 확인
- [ ] 5분봉 12개월 삭제 스크립트 준비

---

## Hybrid Update (2026-02-16)

### 신규 테이블/컬렉션

#### BigQuery: `manual_holdings_lots`
- 용도: 수동입력 매수 lot 저장(평단/수량/매수일)
- 주요 필드:
  - `user_id STRING`
  - `account_id STRING`
  - `symbol STRING`
  - `market STRING`
  - `buy_date DATE`
  - `avg_cost NUMERIC`
  - `quantity INT64`
  - `updated_at TIMESTAMP`
  - `source STRING` (`manual_input` 고정)

#### BigQuery: `sell_recommendations`
- 용도: 보유종목 기반 매도/감축 제안 결과 저장
- 주요 필드:
  - `recommendation_id STRING`
  - `ts_utc TIMESTAMP`
  - `user_id STRING`
  - `symbol STRING`
  - `action STRING` (`SELL|REDUCE|HOLD`)
  - `score FLOAT64`
  - `confidence FLOAT64`
  - `target_reduce_pct FLOAT64`
  - `reason_codes ARRAY<STRING>`
  - `evidence JSON`
  - `requires_confirmation BOOL`

#### MongoDB: `agent_reasoning_logs` (선택)
- 용도: Agent 중간 추론 요약 저장(토큰 절약 위해 압축 텍스트)
- 보존: 30일 TTL 후 BigQuery 요약본만 유지
## Trade Ledger Update (2026-02-16)

### BigQuery: `trade_ledger`
- 용도: 매수/매도 체결 이벤트를 단일 원장으로 저장
- 주요 필드:
  - `trade_id STRING`
  - `user_id STRING`
  - `account_id STRING`
  - `symbol STRING`
  - `market STRING`
  - `side STRING` (`BUY|SELL`)
  - `quantity INT64`
  - `price NUMERIC`
  - `fee NUMERIC`
  - `tax NUMERIC`
  - `executed_at TIMESTAMP`
  - `source STRING` (`broker_fill|manual_input`)
  - `order_id STRING`

### BigQuery: `current_holdings` (뷰 또는 스냅샷)
- 계산 규칙: `net_quantity = SUM(BUY.quantity) - SUM(SELL.quantity)`
- `net_quantity > 0`인 종목만 현재 보유로 간주

### 매도 제안 대상 제한
- `sell_recommendations` 생성 전 `current_holdings`와 조인
- 조인 실패(비보유 종목) 시 제안 생성 금지