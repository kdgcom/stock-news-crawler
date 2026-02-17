# LLM별 AI 주식 트레이딩 시스템 기획 비교 분석

## 1. 분석 대상

| LLM | 파일 | 문서 수 | 분량 | 성격 |
|-----|------|---------|------|------|
| **Claude** | `md/claude/01~05-*.md` | 5개 | ~2,200줄 | 도메인별 심층 설계서 |
| **GPT** | `md/gpt/*.md` | 3개 | ~520줄 | 아키텍처 + MVP 실행 계획 |
| **Gemini** | `md/gemini/ai-trading-system-proposal.md` | 1개 | ~135줄 | 전체 조감도 제안서 |

---

## 2. 각 LLM 접근 방식

### 2.1 Claude — 도메인별 심층 설계

5개 독립 문서로 영역을 나누어 각각을 프로덕션 수준까지 파고든다.

- **아키텍처(01)**: 4계층 + 모니터링 레이어 ASCII 다이어그램. 기술 스택 선정 이유 테이블. 기존 프로젝트(`src/`)에서 확장할 전체 디렉토리 설계. 처리 주기 테이블(실시간~장 마감 후). 5단계 로드맵.
- **데이터 수집(02)**: 국내 5개 + 미국 6개 소스를 개별 나열하고 URL 패턴, Python API 코드 예제, 비용 비교(무료/유료 조합)까지 제시. KIS WebSocket 연결 코드, DART/SEC API 예시. MongoDB 컬렉션 JSON 스키마와 TimescaleDB SQL DDL. KST 기준 장 스케줄. 크롤링 법적 주의사항.
- **AI 에이전트(03)**: Orchestrator + 4개 분석 에이전트(Sentiment/Technical/Fundamental/News) + Signal Aggregator + Risk Manager + Executor의 Multi-Agent 구조. LLM 감성 분석 프롬프트 전문. 계층적 비용 최적화(FinBERT→Haiku→Sonnet). 기술 분석 지표 8종 클래스. 가중치 동적 조정(시장 상황별 4가지 프로필). LLM 기반 최종 검증 프롬프트. 포트폴리오 관리/분산 규칙. BacktestEngine 클래스.
- **인프라(04)**: 하이브리드 배포(로컬 메인+클라우드 백업). Docker Compose YAML 10서비스 전문. Dockerfile. `.env` 20+항목 예시. Prometheus 메트릭 코드. 알림 규칙 8개. JSON 구조화 로깅(6종 파일 분리). 장애 시나리오 6종별 대응표. Health Check. 백업 정책 4종.
- **리스크(05)**: 3계층 구조(하드리미트→동적→AI 검증). HardLimits 클래스(9개 수치). Kill Switch(5개 자동 발동 조건). 손절 3종(고정-5%/트레일링-3%/시간5일). 포트폴리오 레벨 단계적 대응. AI 환각 방어(교차 검증/종목코드 확인). 이상거래 감지. 국내/미국 시장별 리스크 대응표. 환율 리스크. 법규 준수(자본시장법/PDT/Wash Sale Rule). 감사 추적 AuditLogger. 모의투자 체크리스트 20항목. 실전 전환 4단계(5%→10%→30%→목표).

**한마디**: 시스템 완성형의 청사진. 구현 코드 수준의 상세함.

### 2.2 GPT — 실행 가능한 단계적 구축

아키텍처 1개 + MVP 실행 문서 2개로, "데이터 정합성 먼저, 모델은 나중"이라는 실전 원칙을 관철한다.

- **아키텍처**: 5계층(Collector→Streaming Bus→Feature Store→Inference→Execution). 단일 거대 모델 대신 **역할별 소형 모델 조합** 권장(NLP/Event + Price Regime + Signal Fusion). 데이터 스키마에 `event_id`(해시 기반 멱등), `novelty_score`, `reliability_score` 포함. 동일 뉴스 재송출 **군집화**. UTC 저장 원칙 + event-time/ingest-time 분리. 결측은 `missing` 플래그(추정값 덮어쓰기 금지). look-ahead leakage 경고. 포지션 크기 = `budget × confidence × liquidity / volatility`. champion/challenger 모델 배포. 현재 코드(`src/*.py`) 파일별 수정 방향 직접 매핑. 스프레드/슬리피지 임계치 진입 차단.
- **Phase 1 MVP**: In-Scope/Out-of-Scope 분리. 산출물 D1~D5. 기능/비기능 요구사항(이벤트 지연 p95<5초, 중복 정확도>99%). WBS W1~W5 각각 완료 기준. 수용 기준 5개. 테스트 계획(단위/통합/회귀). 4~6주 일정 + 20% 버퍼. Phase 2 진입 조건 3개.
- **실행 체크리스트**: 역할 6개 정의. 마일스톤 M1~M5, 작업 ID 25개. 각 작업에 담당/우선순위/상태/산출물/완료기준 테이블. DoD 4조건. 주간 운영 템플릿. Red Flag 5개. Phase 1 종료 체크박스.

**한마디**: "내일 아침에 스프린트를 시작할 수 있는" 실행 계획.

### 2.3 Gemini — 전체 조감도

단일 문서로 전 영역을 간결하게 훑는다.

- **아키텍처**: 5개 박스 다이어그램(Collection→Processing→AI→Risk→Execution). 각 계층 1~2문장 설명.
- **데이터 수집**: API 우선 접근. 국내는 증권사 API + pykrx. 미국는 yfinance, Polygon.io, Alpha Vantage. 뉴스는 NewsAPI.org + 크롤링 보조. 데이터 스키마 3개 테이블(stocks, stock_prices, news_articles) 간략 제시.
- **AI 분석**: Feature Engineering(기술적 지표 + NLP). **KoBERT**(국내)/FinBERT(미국) 금융 특화 모델 명시. NER, 토픽 모델링(LDA) 언급. 초기 Rule-Based → XGBoost/LightGBM 분류 → LSTM/Transformer 예측 단계.
- **기술 스택**: Python 3.9+, scikit-learn, tensorflow/pytorch, transformers, APScheduler, Celery.
- **로드맵**: Phase 1(MVP 1~3개월, Paper Trading) → Phase 2(ML 도입, 백테스팅, 3~6개월) → Phase 3(실전 소액, 6개월+).
- **리스크**: 5개 항목 목록(비중 제한, 손절, Circuit Breaker, 백테스팅, 점진적 확대).

**한마디**: 프로젝트 킥오프용 1페이지 브리핑. 빠르게 전체를 조망하기 좋다.

---

## 3. 비교 분석

### 3.1 아키텍처 설계

| 항목 | Claude | GPT | Gemini |
|------|--------|-----|--------|
| 구조 | 4계층+모니터링, ASCII 다이어그램 | 5계층+Streaming Bus, 텍스트 계층도 | 5개 박스 다이어그램 |
| 메시지 버스 | Redis Streams | Kafka 또는 Redis Streams | 명시 없음 |
| 저장소 분리 | MongoDB(비정형) + TimescaleDB(시계열) | Raw Lake + Feature Store + Cache 분리 | TimescaleDB/InfluxDB + PostgreSQL/MongoDB |
| 캐시 레이어 | Redis (메시지 큐 겸용) | Redis (최근 N분 상태) | 명시 없음 |
| 고유 특징 | 기존 프로젝트 구조에서 확장하는 디렉토리 설계 | Feature Store / Data Lake 개념 도입, 원문+가공 분리 저장 | InfluxDB 대안 제시 |

### 3.2 데이터 수집

| 항목 | Claude | GPT | Gemini |
|------|--------|-----|--------|
| 소스 구체성 | 11개 소스 개별 나열 + URL, 코드 | 추상("KR/US Collector") | 6개 소스 이름 나열 |
| API 코드 예시 | Alpaca, KIS WebSocket, DART, SEC | 없음 | 없음 |
| 비용 분석 | 무료/유료 조합 비교표 | 없음 | 비용 언급(유/무료 구분) |
| 스키마 | MongoDB JSON + TimescaleDB SQL 전문 | 필드 목록 텍스트 | 3테이블 간략 |
| 중복 제거 | URL + 제목 유사도(0.85) | **event_id 해시 기반 멱등 upsert** | 명시 없음 |
| 시간 처리 | KST 기준 스케줄 | **UTC 원칙 + event-time/ingest-time 분리** | 명시 없음 |
| 뉴스 품질 | 본문 100자 필터, 이상치 감지 | **novelty_score, reliability_score**, **뉴스 군집화** | 명시 없음 |

### 3.3 AI/모델 설계

| 항목 | Claude | GPT | Gemini |
|------|--------|-----|--------|
| 에이전트 구조 | Multi-Agent 7종 | 소형 모델 3종 조합 | 단일 모델 파이프라인 |
| 감성 분석 | **LLM 프롬프트 전문** + **계층적 비용 최적화**(로컬→Haiku→Sonnet) | 규칙 기반 시작 → Phase 2 모델 | **KoBERT/FinBERT** 금융 특화 모델 명시 |
| NLP 기법 | LLM 맥락 분석 | 규칙+약지도(weak supervision) | **NER, 토픽 모델링(LDA)** |
| 기술 분석 | 8종 지표 클래스 + 시그널 규칙 | 언급 수준 | 이동평균/RSI/MACD/볼린저 나열 |
| 의사결정 | 가중 합산 + **동적 조정 4프로필** + **LLM 최종 검증** | score_buy-score_sell + confidence/liquidity/volatility 보정 | 확률 기반 필터링 |
| ML 모델 | BacktestEngine 클래스 | **LightGBM/XGBoost → Transformer/TFT** | **XGBoost/LightGBM → LSTM/Transformer** |
| 고유 아이디어 | LLM 비용 최적화, 가중치 시장 상황별 동적 조정 | **Price Regime 모델**, **look-ahead leakage 경고** | KoBERT, NER, LDA 토픽 모델링 |

### 3.4 리스크 관리

| 항목 | Claude | GPT | Gemini |
|------|--------|-----|--------|
| 분량 | **독립 문서 437줄** | 아키텍처 내 1개 섹션 | 5개 항목 목록 |
| 하드 리미트 | 9개 항목 + 구체 수치 | 종목/일손실/스프레드 3개 | 비중 제한 + 손절 |
| Kill Switch | **전용 클래스, 5개 자동 발동 조건** | "no new position" 원칙 | **Circuit Breaker 패턴** 언급 |
| 손절 | 고정(-5%) + 트레일링(-3%) + 시간(5일) | 언급 수준 | 손절매 원칙 |
| AI 검증 | **환각 방어, 교차 검증, 종목코드 확인** | 없음 (MVP에서 LLM 미사용) | 없음 |
| 법규 | **자본시장법, PDT, Wash Sale Rule** 개별 대응 | 없음 | 없음 |
| 실전 전환 | 4단계 (5%→10%→30%→목표) | Paper→소액→확대 3단계 | 소액 → 점진적 확대 |

### 3.5 인프라/운영

| 항목 | Claude | GPT | Gemini |
|------|--------|-----|--------|
| 배포 | **Docker Compose YAML 10서비스** + Dockerfile | 언급 수준 | 명시 없음 |
| 모니터링 | **Prometheus 메트릭 코드 + Grafana 대시보드 + 알림 8개** | 대시보드 요건 목록 | 대시보드 언급 |
| 로깅 | **JSON 구조화, 6종 분리, 일별 로테이션** | decision_log 스키마 (reason_code) | 명시 없음 |
| 장애 대응 | **6개 시나리오별 감지/자동/수동 대응** | 파서 계약 테스트, fallback 소스 | 시스템 오류 방지 알림 |
| MLOps | 없음 | **champion/challenger 배포, shadow mode, 1분 롤백** | 없음 |

### 3.6 프로젝트 관리

| 항목 | Claude | GPT | Gemini |
|------|--------|-----|--------|
| 로드맵 | Phase 1~5 개요 | **Phase 1을 6주 주간 단위 세분화** | Phase 1~3 개요 |
| 작업 분해 | 없음 | **WBS 5단계 + 마일스톤 5개 + 작업 ID 25개** | 없음 |
| 완료 기준 | 모의투자 체크리스트 형태 | **작업별 완료 기준 + DoD + 수용 기준** | 없음 |
| 역할 정의 | 없음 | **6개 역할 정의 + 작업별 배정** | 없음 |
| 일정 | 순서만 제시 | **주간 일정 + 20% 버퍼** | 월 단위 추정(1~3개월/3~6개월/6개월+) |

---

## 4. 각 LLM의 독보적 강점

### Claude에서만 찾을 수 있는 것
1. **Docker Compose 전체 YAML** — 바로 `docker-compose up` 가능한 수준
2. **리스크 3계층 구조** + Kill Switch 클래스 + 5개 자동 발동 조건
3. **AI 환각 방어** — 교차 모델 검증, 종목코드 실재 확인, 이상거래 패턴 감지
4. **LLM 비용 계층화** — FinBERT → Haiku → Sonnet 단계적 분석
5. **감성 분석 프롬프트 전문** — 즉시 사용 가능한 금융 분석 프롬프트
6. **가중치 동적 조정** — 시장 상황(정상/급등락/실적시즌/이벤트)별 4종 프로필
7. **법규 준수** — 자본시장법, PDT, Wash Sale Rule 대응 테이블
8. **데이터 소스 API 코드** — KIS WebSocket, Alpaca, DART, SEC 실제 코드
9. **환율 리스크 관리** — FxRiskManager 클래스

### GPT에서만 찾을 수 있는 것
1. **event_id 기반 멱등 처리** — `hash(source+url+timestamp)` 중복 제거 아키텍처
2. **event-time / ingest-time 분리** — 지연 분석 가능한 이중 타임스탬프
3. **novelty_score / reliability_score** — 뉴스 새 정보 여부 + 소스 신뢰도 별도 점수화
4. **뉴스 군집화** — 복붙 기사 탐지로 과대반응 방지
5. **Price Regime 모델** — 상승/하락/횡보 + 변동성 상태 분류기
6. **look-ahead leakage 경고** — 백테스트 기사 시각 정합성 함정 명시
7. **실행 관리 체계** — WBS, 마일스톤, 작업 ID, DoD, Red Flag, 주간 템플릿
8. **현재 코드 매핑** — `src/models.py`, `src/scraper.py` 등 파일별 수정 방향
9. **champion/challenger** — shadow mode + 1분 롤백 자동화
10. **스프레드 임계치 진입 차단** — 유동성 부족 시 매매 차단

### Gemini에서만 찾을 수 있는 것
1. **KoBERT 명시** — 한국어 금융 감성 분석에 특화된 모델 지정
2. **NER(개체명 인식)** — 뉴스 본문에서 기업/인물/제품 추출 → 연관 관계 분석
3. **토픽 모델링(LDA)** — 시장 주요 관심사 파악 기법
4. **InfluxDB 대안** — 시계열 DB로 TimescaleDB 외 선택지 제시
5. **Circuit Breaker 패턴** — 기술적 결함 시 전체 주문 중단 용어 사용
6. **간결한 전체 조감도** — 프로젝트 시작 시 팀 공유용 1페이지 브리핑

---

## 5. 각 LLM의 약점

### Claude
- **과설계 위험**: 5개 문서 2,200줄은 초기 MVP에 과도하며, 구현 전 분석 마비(analysis paralysis)를 유발할 수 있음
- **프로젝트 관리 부재**: 작업 분해, 일정, 담당자 배정이 없어 "무엇부터 할지" 불명확
- **데이터 엔지니어링 원칙 약함**: UTC 원칙, event-time 정합성, 멱등 처리 등의 기반이 GPT보다 부족

### GPT
- **데이터 소스 구체성 부족**: "KR/US Collector"라는 추상 레벨에서 멈춤. 실제 API URL이나 코드 없음
- **인프라 설계 부재**: Docker, 모니터링, 백업 등 운영 환경 설계가 빠져 있음
- **AI 환각/법규 미대응**: LLM 활용 시 필수인 환각 방어, 법규 준수가 없음

### Gemini
- **모든 영역이 얕음**: 각 파트가 1~3문장 수준으로 실제 구현에는 부족
- **스키마/인프라 미비**: 실제 사용 가능한 DB 스키마, 배포 구성이 없음
- **리스크 관리 최소**: 5개 항목 목록이 전부이며 구체적 수치나 코드 없음
- **프로젝트 관리 없음**: WBS, 일정, 완료 기준 등이 빠져 있음

---

## 6. 종합 평가

| 평가 축 | Claude | GPT | Gemini |
|---------|--------|-----|--------|
| 아키텍처 설계 완성도 | ★★★★★ | ★★★★☆ | ★★★☆☆ |
| 데이터 수집 구체성 | ★★★★★ | ★★★☆☆ | ★★☆☆☆ |
| AI/모델 설계 깊이 | ★★★★★ | ★★★★☆ | ★★★☆☆ |
| 리스크 관리 | ★★★★★ | ★★★☆☆ | ★★☆☆☆ |
| 인프라/운영 | ★★★★★ | ★★☆☆☆ | ★☆☆☆☆ |
| 데이터 엔지니어링 엄밀성 | ★★★☆☆ | ★★★★★ | ★★☆☆☆ |
| 프로젝트 실행력 | ★★☆☆☆ | ★★★★★ | ★☆☆☆☆ |
| MVP 범위 통제 | ★★☆☆☆ | ★★★★★ | ★★★☆☆ |
| NLP/ML 기법 다양성 | ★★★☆☆ | ★★★☆☆ | ★★★★☆ |
| 초심자 이해 용이성 | ★★★☆☆ | ★★★☆☆ | ★★★★★ |

**한 줄 요약**:
- **Claude**: 완성된 시스템이 어떤 모습인지 보여주는 **설계도**
- **GPT**: 내일부터 무엇을 해야 하는지 보여주는 **실행표**
- **Gemini**: 팀에게 프로젝트를 소개하는 **브리핑 자료**

**최적 조합**: GPT의 실행 체계를 뼈대로, Claude의 설계 자산을 단계별로 채워 넣고, Gemini의 NLP 기법(KoBERT/NER/LDA)을 Phase 2에서 도입하는 것이 가장 현실적이다.
