# 통합 기획: 한국 주식 뉴스·시세 기반 AI 투자 시스템

> Gemini, GPT, Claude 3개 LLM 계획의 장점을 통합한 신규 기획

---

## 1. 통합 원칙

| 출처 | 반영 장점 |
|------|-----------|
| **Gemini** | 단순·명확한 5계층 구조, 단계별 로드맵, 실용적 기술 스택 |
| **GPT** | 데이터 품질·정합성 설계, event_id 멱등, 한국/미국 시장 분리, 구체적 WBS·체크리스트 |
| **Claude** | Multi-Agent 아키텍처, LLM 감성 분석, 3단계 리스크 관리, Kill Switch, 인프라·배포 상세 |

---

## 2. 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────────────────────┐
│  [Collector Layer]                                                       │
│  News Collector (KR/US) | Market Data Collector | Corporate Event        │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  [Streaming Bus]  Redis Streams (MVP) / Kafka (확장)                      │
│  event-time 기준, 중복 제거, event_id 멱등                               │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  [Data & Feature Layer]                                                  │
│  Raw Data Lake | Processed Feature Store | Low-latency Cache (Redis)     │
│  MongoDB(뉴스) | TimescaleDB(시세) | PostgreSQL(메타)                   │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  [AI Multi-Agent Layer]                                                  │
│  Sentiment Analyst | Technical Analyst | Fundamental Analyst | News      │
│  → Signal Aggregator → Risk Manager (최종 관문)                          │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  [Execution Layer]                                                      │
│  KR Broker Adapter | US Broker Adapter | Order Router                    │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  [Monitoring & Governance]                                               │
│  Grafana | Prometheus | Alertmanager | Audit Log                        │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 데이터 설계 (GPT 강점 반영)

### 3.1 뉴스 이벤트 스키마

| 필드 | 설명 |
|------|------|
| `event_id` | 소스+url+timestamp 해시 (멱등, 중복 제거) |
| `market` | KR \| US |
| `symbol` | 표준 티커 |
| `published_at_utc` | UTC 기준 |
| `headline`, `body`, `language` | 원문 |
| `event_type` | 실적, 가이던스, M&A, 규제 등 |
| `sentiment_score` | -1~1 |
| `novelty_score` | 기존 뉴스 대비 신규성 |
| `reliability_score` | 소스 신뢰도 |

### 3.2 시세 데이터 스키마

- `symbol`, `market`, `ts_event`, `open/high/low/close/volume`
- `bid/ask spread`, `volatility_1m/5m`
- `event_time` / `ingest_time` 분리 저장 (지연 분석용)

### 3.3 한국/미국 시장 분리

- 거래시간: KR 정규장/동시호가, US 프리/정규/애프터
- 언어: 한글 형태소, 영문 headline velocity
- 브로커: 공통 인터페이스(`place_order`, `cancel_order`, `get_position`) + 국가별 어댑터

---

## 4. AI Multi-Agent 설계 (Claude 강점 반영)

### 4.1 에이전트 구성

| 에이전트 | 역할 |
|----------|------|
| **Sentiment Analyst** | LLM 기반 감성 분석 (계층화: Haiku→Sonnet) |
| **Technical Analyst** | MA, RSI, MACD, 볼린저 밴드 |
| **Fundamental Analyst** | PER, PBR, ROE, 실적 |
| **News Analyst** | 뉴스 빈도, 중요도 |
| **Signal Aggregator** | 가중 합산, 시장 상황별 가중치 조정 |
| **Risk Manager** | 최종 관문, 리스크 게이트 |

### 4.2 감성 분석 파이프라인

1. 로컬 모델(FinBERT/KoBERT) 1차 필터
2. 관심 종목·영향력 있는 뉴스만 LLM 분석
3. 강한 시그널 시 고성능 모델 재검증
4. 캐싱으로 동일 뉴스 재분석 방지

### 4.3 신호 융합 (GPT Regime 모델 반영)

- `trend_state`, `vol_state`, `liquidity_state` 반영
- 변동성 과열 구간 진입 크기 축소
- look-ahead leakage 엄격 차단

---

## 5. 리스크 관리 (Claude + GPT 통합)

### 5.1 3단계 구조

| 단계 | 내용 |
|------|------|
| **Level 1** | 하드 리미트 (단일 주문 한도, 일일 손실 한도, Kill Switch) |
| **Level 2** | 동적 리스크 (변동성 기반 포지션 축소, 연속 손실 쿨다운) |
| **Level 3** | AI 검증 (신뢰도 임계값, 환각 방어, 이상 거래 감지) |

### 5.2 리스크 게이트 (GPT)

- 종목당/섹터당 최대 노출
- 일 손실 한도, 연속 손실 쿨다운
- 이벤트 직후 n초 주문 금지
- 스프레드/슬리피지 임계치 초과 시 진입 금지
- 거래소 이상(서킷브레이커 등) 시 전면 중지

### 5.3 장애 시 기본값

- **always-safe**: `no new position`
- 신호 생성과 주문 실행 사이 독립 리스크 프로세스

---

## 6. 단계별 로드맵 (Gemini + GPT 통합)

### Phase 1: MVP (4~6주)

**목표**: 데이터 정합성·파이프라인 안정성

- KR/US 뉴스 + 1분봉 시세 수집
- event_id 멱등, 중복 제거
- 규칙 기반 sentiment + BUY/SELL/HOLD
- Paper Trading만, 실제 주문 없음
- 2주 이상 paper 운영 검증

**산출물**: raw_news_events, enriched_news_events, market_1m_bars, decision_logs

### Phase 2: 모델 고도화 (8~12주)

**목표**: 신호 품질 개선

- 이벤트 분류기, Regime 모델, Fusion 모델
- LLM 감성 분석 도입
- 리스크 게이트 고도화
- Walk-forward 백테스트 자동화

### Phase 3: 실거래 연동 (12주+)

**목표**: 운영 가능한 자동화

- 증권사 API 연동 (소액)
- 시장별 전략 분화
- 포트폴리오 레벨 최적화
- 모의투자 3개월 이상 검증 후 실전 전환

---

## 7. 기술 스택

| 영역 | 기술 |
|------|------|
| **언어** | Python 3.11+ |
| **스트리밍** | Redis Streams (MVP) → Kafka (확장) |
| **저장소** | MongoDB(뉴스), TimescaleDB(시세), Redis(캐시) |
| **AI/ML** | HuggingFace, PyTorch, LightGBM, Claude/OpenAI API |
| **오케스트레이션** | APScheduler, Celery |
| **배포** | Docker Compose |
| **모니터링** | Prometheus, Grafana, Alertmanager |

---

## 8. 현재 프로젝트(stock-news-crawler) 확장 계획

### 8.1 기존 모듈 확장

- `scraper.py`: 커넥터 + 정규화 분리, `market`, `symbol`, `published_at_utc` 추가
- `models.py`: `NewsArticle` → `RawNewsEvent` + `EnrichedNewsEvent`
- `news_analyzer.py`: `classify_event_type`, `score_sentiment`, `estimate_horizon` 분해
- `data_manager.py`: upsert(event_id), 인덱스 최적화

### 8.2 신규 모듈

- `market_data_collector.py`
- `signal_engine.py`
- `risk_engine.py`
- `execution_router.py`
- `backtest/`
- `collectors/`, `analyzers/`, `agents/`, `brokers/`

---

## 9. 핵심 원칙 요약

1. **데이터 품질 우선**: event_id 멱등, event-time 정합성, 중복 제거
2. **리스크가 최종 결정권**: 신호 생성과 주문 실행 사이 독립 검증
3. **점진적 전환**: 데이터 검증 → Paper Trading → 소액 실거래
4. **한국/미국 분리 설계**: 거래시간, 언어, 브로커 어댑터
5. **감사 추적**: 모든 의사결정에 reason_code, 판단 근거 기록
