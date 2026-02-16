# 3개 LLM 계획 비교 분석

## 1. 분석 대상

| LLM | 경로 | 문서 수 | 주요 내용 |
|-----|------|---------|-----------|
| **Gemini** | `md/gemini/` | 1개 | ai-trading-system-proposal.md |
| **GPT** | `md/gpt/` | 3개 | 아키텍처, Phase1 MVP 구현, 실행 체크리스트 |
| **Claude** | `md/claude/` | 5개 | 아키텍처, 데이터수집, AI에이전트, 인프라, 리스크관리 |

---

## 2. Gemini 계획 분석

### 2.1 핵심 특징

- **아키텍처**: 5계층 선형 구조 (Data Collection → Processing → AI Analysis → Risk Management → Execution)
- **데이터 수집**: API 우선, 크롤링 보조 (BeautifulSoup, Scrapy)
- **저장소**: TimescaleDB/InfluxDB(시계열), PostgreSQL/MongoDB(정형·비정형)
- **AI 접근**: KoBERT/FinBERT 감성분석, 기술적 지표(MA, RSI, MACD), 규칙 기반 → XGBoost/LSTM
- **로드맵**: Phase 1(1~3개월) MVP → Phase 2(3~6개월) ML 도입 → Phase 3(6개월+) 실전

### 2.2 장점

- 구조가 단순하고 이해하기 쉬움
- 단계별 로드맵이 명확함
- 기술 스택이 실용적이고 검증됨
- Paper Trading 우선 원칙 명시
- Circuit Breaker 등 기본 리스크 관리 포함

### 2.3 단점

- 구현 수준의 세부사항이 부족함
- 스트리밍/이벤트 처리 아키텍처 미제시
- 한국/미국 시장 차이 반영 부족
- 실행 가능한 WBS나 체크리스트 없음

---

## 3. GPT 계획 분석

### 3.1 핵심 특징

- **아키텍처**: 이벤트 기반 스트리밍 (Collector → Kafka/Redis Streams → Feature Store → Inference → Execution)
- **데이터 설계**: event_id 기반 멱등, event-time/ingest-time 분리, novelty_score, reliability_score
- **모델 계층**: NLP/Event 모델, Regime 모델(가격 체제), Fusion 모델(신호 융합) 분리
- **리스크**: 신호 생성과 주문 실행 사이 독립 리스크 프로세스, always-safe 기본값
- **현재 프로젝트 연계**: stock-news-crawler 구조에 맞춘 구체 모듈/액션 제안

### 3.2 장점

- 데이터 품질·정합성 강조 (중복 제거, look-ahead leakage 방지)
- 한국/미국 시장 분리 설계 (거래시간, 언어, 브로커 어댑터)
- 역할별 소형 모델 조합으로 확장성 확보
- Phase 1 MVP 4~6주 WBS, 수용 기준, 테스트 계획 구체적
- 실행 체크리스트(마일스톤, 담당, DoD)로 운영 가능
- 백테스트 시 이벤트 시각 정합성 강조

### 3.3 단점

- Multi-Agent나 LLM 활용 전략은 상대적으로 약함
- 인프라·배포 상세(예: Docker) 부족
- AI 환각 검증 등 AI 특화 리스크 대응 미흡

---

## 4. Claude 계획 분석

### 4.1 핵심 특징

- **아키텍처**: Multi-Agent (Orchestrator → Sentiment/Technical/Fundamental/News Analyst → Signal Aggregator → Risk Manager → Executor)
- **감성 분석**: LLM 기반(Claude API), 프롬프트 설계, 계층화(Haiku→Sonnet), 비용 최적화
- **인프라**: Redis Streams, MongoDB, TimescaleDB, Docker Compose, Grafana/Prometheus
- **리스크**: 3단계(시스템 안전장치/동적 리스크/AI 검증), Kill Switch, AI 환각 검증
- **규정 준수**: 자본시장법, Pattern Day Trader, Wash Sale 등 시장별 고려

### 4.2 장점

- Multi-Agent로 관심사 분리·확장성 확보
- LLM 감성 분석 파이프라인·비용 최적화 전략 구체적
- Docker Compose, 모니터링, 로깅 등 운영 인프라 상세
- 리스크 3단계, Kill Switch, AI 환각 방어 등 리스크 설계가 체계적
- 시장별(국내/미국) 규정·리스크 고려
- 감사 추적(Audit Trail) 설계

### 4.3 단점

- 데이터 스키마·event_id 등 데이터 정합성 설계는 GPT보다 단순
- Phase 1 MVP의 구체적 WBS·일정 부족
- 스트리밍 버스(Kafka 등) 설계는 Redis Streams 수준에 그침

---

## 5. 종합 비교표

| 항목 | Gemini | GPT | Claude |
|------|--------|-----|--------|
| **아키텍처 복잡도** | 단순(5계층) | 중간(스트리밍) | 높음(Multi-Agent) |
| **데이터 품질 설계** | 보통 | 매우 상세 | 보통 |
| **AI/ML 전략** | 규칙→ML 단계적 | 역할별 모델 분리 | LLM+Multi-Agent |
| **실행 가능성** | 낮음 | 높음(WBS, 체크리스트) | 중간 |
| **인프라/배포** | 미제시 | 보통 | 상세(Docker 등) |
| **리스크 관리** | 기본 | 상세(게이트) | 매우 상세(3단계, Kill Switch) |
| **한국/미국 분리** | 약함 | 강함 | 강함 |
| **현재 프로젝트 연계** | 없음 | 강함 | 보통 |

---

## 6. 결론

- **Gemini**: 전체 그림과 로드맵이 명확하나, 실행 수준의 구체성 부족
- **GPT**: 데이터 정합성·실행 계획·현재 코드베이스 연계가 강함
- **Claude**: AI 활용·리스크·운영 인프라 설계가 가장 상세함

각 계획의 장점을 통합하면, **데이터 품질(GPT) + AI/리스크 설계(Claude) + 단계적 로드맵(Gemini)** 을 결합한 통합 기획이 적합하다.
