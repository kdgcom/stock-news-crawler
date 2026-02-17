# AI 주식 트레이딩 시스템 — 통합 기획서

> Claude, GPT, Gemini 세 LLM의 강점을 결합한 통합 계획.
>
> | 출처 | 차용 항목 |
> |------|----------|
> | **GPT** | 실행 관리(WBS/DoD/수용 기준), 데이터 엔지니어링(event_id 멱등, UTC, event-time 분리, novelty/reliability, 뉴스 군집화), MVP 범위 통제, 현재 코드 연계, Price Regime, champion/challenger, 스프레드 진입 차단 |
> | **Claude** | 운영 설계(Docker/모니터링/장애 대응/백업), 리스크 3계층(하드리미트+동적+AI 검증), Kill Switch, 데이터 소스 구체성, Multi-Agent, LLM 비용 최적화, 가중치 동적 조정, 감성 분석 프롬프트, 법규 준수, 감사 추적 |
> | **Gemini** | KoBERT/FinBERT 금융 특화 모델, NER(개체명 인식), 토픽 모델링(LDA), Circuit Breaker 개념 |

---

## 1. 시스템 목표

국내(KRX) + 미국(NYSE/NASDAQ) 주식 시장 대상:

1. 뉴스/공시/시세를 실시간으로 수집하여 정합하게 저장한다.
2. 다층 AI 분석(감성/기술/재무)을 종합하여 매수/매도/관망을 결정한다.
3. 리스크 엔진이 **최종 의사결정권자**로서 모든 거래를 통제한다.
4. 모의투자 → 소액 → 점진적 증액 순서로 실전에 진입한다.

**3대 원칙**:
- **데이터 품질 > 모델 정확도 > 수익 최적화** 순서로 확보한다.
- 장애 시 기본값은 **`no new position`** (안전 모드).
- 모든 의사결정은 **재현 가능한 로그**(reason_code + input_features_hash)로 남긴다.

---

## 2. 전체 아키텍처

```
[Collector Layer]
  News (KR: 네이버금융/한경/DART, US: Alpaca/MarketAux/SEC)
  Price (KR: KIS API, US: Alpaca/yfinance)
  Corporate Events (DART 공시, SEC Filing)
        │
        ▼
[Streaming Bus — Redis Streams]
  event-time 기준 이벤트 스트림
        │
        ▼
[Storage Layer]
  MongoDB ── raw_news_events + enriched_news_events
  TimescaleDB ── market_1m_bars (시계열)
  Redis ── 최근 N분 캐시 + 실시간 상태
        │
        ▼
[Inference & Decision Layer]
  Phase 1: 규칙 기반 (키워드 감성 + RSI/SMA)
  Phase 2: Multi-Agent + 금융 NLP
            ├── Sentiment Agent (KoBERT/FinBERT → Haiku → Sonnet)
            ├── Technical Agent (지표 8종)
            ├── Fundamental Agent (PER/PBR/ROE)
            └── News Agent (NER + novelty + reliability + 군집화)
           → Signal Aggregator (가중 합산 + 동적 조정)
  Phase 3: Price Regime + Fusion 모델 (LightGBM → Transformer)
        │
        ▼
[Risk Gate — 독립 프로세스]
  Level 1: 하드 리미트 (절대 한도)
  Level 2: 동적 리스크 (변동성/연속손실/스프레드)
  Level 3: AI 판단 검증 (환각 방어)
  Circuit Breaker / Kill Switch (비상 정지)
        │
        ▼
[Execution Layer]
  Phase 1: Paper Trading
  Phase 2+: KR Broker (KIS) + US Broker (Alpaca)
        │
        ▼
[Monitoring & Governance]
  Prometheus + Grafana  |  Slack/Telegram 알림
  감사 로그 (decision_logs)  |  champion/challenger 모델 관리
```

---

## 3. 데이터 설계

### 3.1 핵심 원칙

| # | 원칙 | 출처 |
|---|------|------|
| 1 | 모든 시간 **UTC 저장**, 화면에서만 현지시간 변환 | GPT |
| 2 | **event_id** 기반 멱등: `hash(source + url + published_at_utc)` → upsert | GPT |
| 3 | **event-time + ingest-time** 분리 저장 → 지연 분석 | GPT |
| 4 | 결측 구간은 `missing` 플래그 — 추정값으로 덮지 않음 | GPT |
| 5 | 복붙 기사 **군집화** → 과대반응 방지 | GPT |
| 6 | 원문(raw) + 분석 결과(enriched) **분리** 저장 | Claude+GPT |

### 3.2 뉴스 스키마

```javascript
// raw_news_events
{
    event_id: "hash",           // unique index
    market: "KR",               // KR | US
    symbol: "005930",
    headline: "삼성전자 실적 호전",
    body: "...",
    language: "ko",             // ko | en
    source_name: "네이버금융",
    source_type: "news",        // news | disclosure | sns
    published_at_utc: ISODate,
    ingested_at_utc: ISODate,
    url: "https://..."
}

// enriched_news_events
{
    event_id: "hash",
    event_type: "earnings",     // earnings | m_and_a | regulation | product | lawsuit ...
    sentiment_score: 0.72,      // -1.0 ~ 1.0
    confidence: 0.85,
    impact_horizon: "short_term",
    novelty_score: 0.9,         // (GPT)
    reliability_score: 0.95,    // (GPT)
    cluster_id: "cluster_abc",  // 뉴스 군집 (GPT)
    entities: [                 // NER 결과 (Gemini)
        { name: "삼성전자", type: "company", ticker: "005930" }
    ],
    topic_tags: ["반도체", "실적"],  // 토픽 모델링 (Gemini)
    affected_symbols: ["005930", "000660"],
    summary: "...",
    analyzed_by: "rule_v1",
    analyzed_at_utc: ISODate
}
```

### 3.3 시세 스키마 (TimescaleDB)

```sql
CREATE TABLE market_1m_bars (
    ts_event     TIMESTAMPTZ NOT NULL,
    ts_ingest    TIMESTAMPTZ NOT NULL,
    symbol       TEXT NOT NULL,
    market       TEXT NOT NULL,
    open         DECIMAL(15,4),
    high         DECIMAL(15,4),
    low          DECIMAL(15,4),
    close        DECIMAL(15,4),
    volume       BIGINT,
    vwap         DECIMAL(15,4),
    spread_pct   DECIMAL(8,6),
    halt_flag    BOOLEAN DEFAULT FALSE,
    missing_flag BOOLEAN DEFAULT FALSE
);
SELECT create_hypertable('market_1m_bars', 'ts_event');
CREATE INDEX ON market_1m_bars (market, symbol, ts_event DESC);
```

### 3.4 의사결정 로그

```javascript
{
    decision_id: "uuid",
    ts_utc: ISODate,
    symbol: "005930",
    market: "KR",
    decision: "BUY",
    score: 0.67,
    input_features_hash: "sha256",   // 재현성 (GPT)
    model_version: "rule_v1",
    reason_codes: ["HIGH_SENTIMENT", "OVERSOLD_RSI"],
    reasons: {
        sentiment: { score: 0.72, source: "뉴스 5건" },
        technical: { score: 0.55, source: "RSI=32" }
    },
    risk_check: { passed: true, checks: ["position:OK", "daily_loss:OK", "spread:OK"] },
    order_result: "filled"
}
```

### 3.5 기업 마스터 데이터

- 한국/미국 종목 코드 맵 테이블
- 동음이의 기업명 disambiguation 규칙 (GPT)
- 상장폐지, 티커변경, 액면분할 이력 (GPT)

---

## 4. 데이터 수집 (Claude 소스 + GPT 정규화)

### 국내

| 소스 | 방법 | 비용 | Phase |
|------|------|------|-------|
| 네이버 금융 뉴스 | HTML 크롤링 | 무료 | 1 |
| DART 전자공시 | OpenAPI | 무료 | 1 |
| KIS 시세 | REST + WebSocket | 무료(계좌) | 1 |
| 한국경제/매일경제 | RSS | 무료 | 2 |

### 미국

| 소스 | 방법 | 비용 | Phase |
|------|------|------|-------|
| Alpaca News | REST API | 무료 티어 | 1 |
| SEC EDGAR | REST API | 무료 | 1 |
| yfinance | 라이브러리 | 무료 | 1 |
| MarketAux | REST API | 무료 티어 | 2 |

### 공통 규칙
- `robots.txt` / 이용약관 준수
- 지수 백오프 재시도 (최대 5회)
- source timestamp + ingest timestamp 동시 저장
- 정규화 어댑터 → 표준 스키마 변환
- 수집기 단일 실패가 파이프라인 전체로 전파되지 않도록 격리

---

## 5. 분석 엔진 — 단계별 진화

### Phase 1: 규칙 기반

**감성**: 한글/영문 키워드 사전 분리, headline 우선 + body 보정

**기술**: RSI(14), SMA 20/50 크로스, 거래량 급증(평균 2배)

**의사결정**:
```python
if confidence < C_MIN:          "HOLD"
elif risk_gate_blocked:         "HOLD"
elif combined_score > TH_BUY:   "BUY"
elif combined_score < TH_SELL:  "SELL"
else:                           "HOLD"

position_size = budget × confidence × liquidity / volatility
```

### Phase 2: Multi-Agent + 금융 NLP

Claude의 에이전트 구조 + Gemini의 NLP 기법:

```
Orchestrator
  ├── Sentiment Agent
  │     ① KoBERT(국내) / FinBERT(미국) — 빠른 필터링 (Gemini)
  │     ② Claude Haiku — 관심 종목 상세 분석 (Claude)
  │     ③ Claude Sonnet — 강한 시그널 재검증 (Claude)
  │
  ├── Technical Agent — SMA/EMA/MACD/RSI/Bollinger/ATR/OBV/VWAP (Claude)
  │
  ├── Fundamental Agent — PER/PBR/ROE + 공시 분석
  │
  └── News Agent
        NER: 기업/인물/제품 추출 (Gemini)
        토픽 모델링(LDA): 시장 관심사 (Gemini)
        novelty_score + reliability_score (GPT)
        뉴스 군집화 (GPT)
```

**Signal Aggregator** — 시장 상황별 동적 가중치 (Claude):

| 상황 | 감성 | 기술 | 재무 | 뉴스 |
|------|------|------|------|------|
| 정상 | 0.30 | 0.35 | 0.20 | 0.15 |
| 급등락 | 0.15 | 0.45 | 0.10 | 0.30 |
| 실적 시즌 | 0.20 | 0.20 | 0.45 | 0.15 |
| 이벤트 | 0.40 | 0.20 | 0.10 | 0.30 |

### Phase 3: 고도화

- **Price Regime 모델** (GPT): HMM/Gradient Boosting → 상승/하락/횡보 + 변동성
- **Signal Fusion**: LightGBM/XGBoost → 시계열 Transformer (GPT+Gemini)
- 강화학습(RL) 기반 가중치 최적화 (Claude)
- **champion/challenger 배포** (GPT): shadow mode → 1분 롤백

---

## 6. 리스크 관리 — 3계층 (Claude) + 실전 규칙 (GPT)

### Level 1: 하드 리미트

```python
MAX_SINGLE_ORDER_KRW = 5_000_000     # 500만원
MAX_SINGLE_ORDER_USD = 3_000
MAX_ORDERS_PER_DAY = 50
MAX_DAILY_LOSS_PCT = -0.03           # -3%
MAX_WEEKLY_LOSS_PCT = -0.05
MAX_TOTAL_DRAWDOWN_PCT = -0.15       # MDD -15%
MAX_SINGLE_STOCK_PCT = 0.10
MAX_SECTOR_PCT = 0.30
MAX_TOTAL_POSITIONS = 20
MIN_CASH_RESERVE_PCT = 0.20
MAX_LLM_DAILY_COST_USD = 20.0
```

### Level 2: 동적 리스크

| 조건 | 대응 |
|------|------|
| VIX/변동성 과열 | 포지션 자동 축소 |
| 3연속 손실 | 1시간 매수 쿨다운 |
| 이벤트 직후 n초 | 주문 금지 (뉴스 오인식 완충) |
| 스프레드 > 임계치 | 진입 금지 (GPT) |
| 서킷브레이커/거래정지 | 전면 중지 |

### Level 3: AI 판단 검증 (Phase 2+)

- 신뢰도 < 0.6 → 무시
- 극단적 점수(±0.9) → 교차 검증 (Claude)
- 종목코드 실재 확인 (Claude)
- 근거 최소 2개 이상 일치 (Claude)
- 시장 급락 중 강한 매수 → 신뢰도 감소

### Kill Switch / Circuit Breaker

```python
AUTO_TRIGGER = [
    "일일 손실 한도 초과",
    "MDD 한도 초과",
    "증권사 API 연속 실패 5회",
    "시스템 이상 동작 감지",
    "수동 작동 (사용자)",
]
# → 미체결 전량 취소 → 알림 → 감사 로그
```

### 손절 전략

| 유형 | 조건 |
|------|------|
| 고정 | 매수가 대비 -5% |
| 트레일링 | 고점 대비 -3% |
| 시간 | 5일 보유 + 수익률 < -2% |

---

## 7. 인프라 — Phase별 점진 도입 (Claude 설계)

### Phase 1: 최소 구성

```yaml
services:
  mongodb:
    image: mongodb/mongodb-community-server:latest
    ports: ["27017:27017"]
    volumes: [mongodb_data:/data/db]
    restart: always
  timescaledb:
    image: timescale/timescaledb:latest-pg16
    ports: ["5432:5432"]
    restart: always
  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
    restart: always
  app:
    build: .
    env_file: .env
    depends_on: [mongodb, timescaledb, redis]
    restart: always
```

### Phase 2+: 운영 강화

- 서비스 분리 (news-crawler / price-feeder / ai-agent / executor)
- Prometheus + Grafana 모니터링
- Slack / Telegram 알림
- 백업 (MongoDB: 매일, TimescaleDB: 매주, 거래기록: 실시간)
- 하이브리드 배포 (로컬 메인 + 클라우드 백업)

### 핵심 모니터링 지표

| 카테고리 | 지표 | 경보 |
|---------|------|------|
| 데이터 | 수집 지연 p95 | > 5초 |
| 데이터 | 중복률 | > 1% |
| 트레이딩 | 일일 손실 | > -3% 중단 |
| 트레이딩 | MDD | > -15% Kill Switch |
| 시스템 | 수집 공백 | > 5분 |
| 비용 | LLM 일일 | > $10 모델 전환 |

---

## 8. 검증 (GPT 엄밀성 + Claude 지표)

### 백테스팅 규칙
- **event-time 기준 체결** — look-ahead leakage 엄격 차단 (GPT)
- 수수료 / 세금 / 슬리피지 반영 (GPT)
- 거래 불가 구간(정지, 호가 공백, 동시호가) 반영 (GPT)
- **검증 절차**: in-sample → out-of-sample → walk-forward → paper 4~8주 (GPT)

### 평가 지표
| 지표 | 목표 |
|------|------|
| 벤치마크 대비 | > KOSPI / S&P 500 |
| CAGR | > 15% |
| 샤프 | > 1.5 |
| MDD | < -15% |
| 승률 | > 55% |
| 손익비 | > 1.5 |

---

## 9. 법규 준수 (Claude)

| 법규 | 대응 |
|------|------|
| 자본시장법 (시세조종 금지) | 이상거래 패턴 자동 감지 |
| 개인정보보호법 | API 키/계좌 `.env` 관리 |
| Pattern Day Trader | 5일 내 4회 → $25k 필요 → 빈도 모니터링 |
| Wash Sale Rule | 30일 이내 재매수 → 매매 기록 추적 |

감사 로그: 모든 결정의 근거(입력, 모델 버전, 프롬프트, 리스크 체크)를 write-once audit 컬렉션에 영구 보존.

---

## 10. 현재 코드 수정 방향 (GPT)

### 기존 파일

| 파일 | 변경 |
|------|------|
| `src/models.py` | `NewsArticle` → `RawNewsEvent` + `EnrichedNewsEvent`. `event_id`, `market`, `symbol`, `language`, 이중 타임스탬프 추가 |
| `src/scraper.py` | 사이트별 파서 → 커넥터 + 정규화 어댑터. 표준 스키마 출력 |
| `src/news_analyzer.py` | `analyze_price_impact` → `classify_event_type` + `score_sentiment` + `estimate_horizon` 분해 |
| `src/data_manager.py` | upsert(event_id) 지원. 시간/종목 인덱스 최적화 |

### 신규 모듈

```
src/
├── collectors/
│   ├── base_collector.py          # 공통 인터페이스 + 재시도
│   ├── kr_news_collector.py       # 네이버 + DART
│   ├── us_news_collector.py       # Alpaca + SEC
│   ├── kr_price_collector.py      # KIS API
│   └── us_price_collector.py      # yfinance / Alpaca
├── analyzers/
│   ├── rule_sentiment.py          # Phase 1: 키워드
│   ├── rule_technical.py          # Phase 1: RSI/SMA
│   ├── ner_extractor.py           # Phase 2: 개체명 인식 (Gemini)
│   ├── topic_analyzer.py          # Phase 2: LDA (Gemini)
│   └── signal_engine.py           # BUY/SELL/HOLD
├── risk/
│   ├── hard_limits.py
│   ├── risk_gate.py
│   └── kill_switch.py
├── execution/
│   ├── paper_executor.py          # Phase 1
│   └── base_broker.py             # 공통 인터페이스
├── monitoring/
│   ├── metrics.py
│   └── daily_report.py
└── utils/
    ├── event_id.py                # 멱등 해시
    ├── normalizer.py              # 정규화
    └── logger.py                  # JSON 구조화 로깅
```

---

## 11. 단계별 로드맵

### Phase 1: 데이터 + 파이프라인 안정화 (6주)

**목표**: 데이터 정합성 확보. Paper Trading 2주 연속 운영.

| 주차 | 마일스톤 | 핵심 작업 | 완료 기준 |
|------|---------|----------|----------|
| W1 | M1. 스키마/저장소 | 모델 정의, 인덱스, upsert, event_id | 동일 ID 100회 → 1건 |
| W2-3 | M2. 수집기 4종 | KR/US 뉴스, KR/US 시세, 정규화 어댑터 | 24시간 무중단 |
| W4 | M3. 분석/신호 | 키워드 감성, RSI/SMA 기술, B/S/H 로직 | 샘플 라벨 80% 일치 |
| W5 | M4. 리스크+Paper | 게이트 3종, paper 체결, PnL | 한도 시 100% 차단 |
| W6 | M5. 관측+안정화 | 메트릭, 일일 리포트, 경보 | 2주 무중단 paper |

**DoD**: 코드 반영 + 테스트 검증 + 실패 케이스 처리 + 문서 업데이트

**Phase 1 종료 조건**:
- [ ] 2주+ paper 연속 운영
- [ ] 중복률 < 1%
- [ ] 리스크 위반 거래 0건
- [ ] 의사결정 재현 가능 (로그 기반)
- [ ] 장애 대응 문서 확정

**Red Flags**: 6시간+ 수집 중단 / 중복률 2배 급증 / decision_log 누락 / risk gate 우회

---

### Phase 2: 모델 고도화 + 운영 강화 (8~12주)

- **KoBERT/FinBERT** 금융 감성 분석 도입 (Gemini)
- LLM 계층화: 로컬 → Haiku → Sonnet (Claude)
- **NER + 토픽 모델링(LDA)** (Gemini)
- Multi-Agent 아키텍처 (Claude)
- 기술 분석 확장: MACD/Bollinger/ATR/OBV (Claude)
- 재무 분석: PER/PBR/ROE (Claude)
- walk-forward 백테스트 자동화 (GPT)
- Docker 서비스 분리 + Prometheus/Grafana (Claude)
- 알림 Slack/Telegram (Claude)

**종료 조건**: 백테스트 샤프 > 1.0 / 모니터링 가동 / Kill Switch 정상

---

### Phase 3: 실전 진입 (12주+)

- 증권사 API 연동 (KIS 모의→실전, Alpaca Paper→Live)
- **단계적 전환**: 5%(1개월) → 10%(1개월) → 30%(2개월) → 목표 (Claude)
- Price Regime 모델 (GPT)
- 시장별(KR/US) 전략 분화
- 환율 리스크 모니터링 (Claude)

---

### Phase 4: 고도화

- Signal Fusion (LightGBM → Transformer) (GPT+Gemini)
- 강화학습 기반 전략 최적화 (Claude)
- 대안 데이터 (SNS, 검색 트렌드) (Claude)
- champion/challenger 자동화 (GPT)
- 클라우드 백업 (Claude)

---

## 12. 핵심 원칙

| # | 원칙 |
|---|------|
| 1 | **잃지 않는 것이 첫 번째** — 수익보다 자본 보존 |
| 2 | **데이터가 모델보다 먼저** — 정합한 데이터 없이 좋은 모델 없다 |
| 3 | **점진적으로** — 규칙 → KoBERT/FinBERT → LLM → 소액 → 증액 |
| 4 | **AI를 신뢰하되 검증** — 리스크 계층 통과 필수 |
| 5 | **모든 것을 기록** — reason_code + input_hash + audit log |
| 6 | **장애 = 안전 모드** — 기본값은 "새 포지션 없음" |
| 7 | **최악을 가정** — Kill Switch, Circuit Breaker 항시 준비 |
