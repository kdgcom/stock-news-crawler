# AI-Powered Stock Trading Agent: System Architecture Proposal

## 1. 개요 (Overview)

본 문서는 실시간으로 대한민국 및 미국 주식 시장의 뉴스, 주가 데이터를 수집하고, 이를 AI 에이전트가 분석하여 매수/매도 결정을 내리는 자동화 트레이딩 시스템의 아키텍처 및 구현 방안을 제안합니다. 이 시스템의 목표는 데이터에 기반한 객관적이고 신속한 트레이딩을 통해 시장 변동성에 효과적으로 대응하고 투자 효율성을 극대화하는 것입니다.

---

## 2. 시스템 아키텍처 (System Architecture)

시스템은 크게 5개의 핵심 계층으로 구성됩니다.

```
+---------------------------+      +--------------------------+      +--------------------------+
|   Data Collection Layer   |----->| Data Processing & Storage|----->|   AI Analysis & Decision |
| (Crawlers & API Clients)  |      |         Layer            |      |          Layer           |
+---------------------------+      +--------------------------+      +--------------------------+
             |                                                                   |
             | (Real-time Market Data)                                           | (Buy/Sell Signals)
             |                                                                   V
+---------------------------+      +--------------------------+      +--------------------------+
|   Brokerage API Interface |<-----|    Execution Layer       |<-----|   Risk Management Layer  |
|   (증권사 API 연동)      |      |  (주문 실행 및 관리)     |      |    (포지션, 손절 관리)   |
+---------------------------+      +--------------------------+      +--------------------------+
```

1.  **데이터 수집 계층 (Data Collection Layer):** 주가, 재무, 뉴스 등 필요한 모든 원시 데이터를 외부 소스(API, 웹사이트)로부터 가져옵니다.
2.  **데이터 처리 및 저장 계층 (Data Processing & Storage Layer):** 수집된 원시 데이터를 정제, 가공하고 구조화하여 데이터베이스에 저장합니다.
3.  **AI 분석 및 결정 계층 (AI Analysis & Decision Layer):** 저장된 데이터를 바탕으로 AI 모델이 시장을 분석하고 특정 종목에 대한 매수/매도/관망 신호를 생성합니다.
4.  **리스크 관리 계층 (Risk Management Layer):** AI가 생성한 신호에 기반하여, 사전에 정의된 리스크 관리 규칙(예: 투자 비중, 손절매 원칙)을 적용합니다.
5.  **실행 계층 (Execution Layer):** 리스크 관리 계층을 통과한 최종 주문을 증권사 API를 통해 실제로 제출하고 체결 여부를 관리합니다.

---

## 3. 세부 설계 방안

### 3.1. 데이터 수집 계층 (Data Collection)

안정적인 데이터 수급을 위해 웹 크롤링보다는 API 사용을 우선적으로 고려합니다.

*   **주가 데이터 (시세, 호가, 체결 정보):**
    *   **국내:** 한국투자증권, 대신증권 등에서 제공하는 실시간 API 활용. API 사용이 어려울 경우, `pykrx` 라이브러리 등을 보조적으로 사용.
    *   **미국:** `yfinance` (무료, 약간의 딜레이), [Polygon.io](http://polygon.io/), [Alpha Vantage](http://alpha-vantage.co/) (유료, 실시간) 등의 API 활용.
    *   **수집 항목:** 시가, 고가, 저가, 종가, 거래량 (O-H-L-C-V), 호가, 체결 데이터 등.

*   **뉴스 데이터 (News Data):**
    *   **국내:** 네이버 금융 뉴스, 연합인포맥스 등 주요 경제 뉴스 포털. API가 없을 경우 `BeautifulSoup`, `Scrapy`를 이용한 웹 크롤링.
    *   **미국:** Reuters, Bloomberg, MarketWatch 등. [NewsAPI.org](http://newsapi.org/) 와 같은 뉴스 애그리게이터 API 사용을 권장.
    *   **수집 항목:** 기사 제목, 본문, 게시 시간, 출처.

### 3.2. 데이터 처리 및 저장 계층 (Processing & Storage)

*   **데이터베이스:**
    *   **시계열 데이터 (주가):** 대용량 시계열 데이터 처리에 용이한 **TimescaleDB** (PostgreSQL 확장) 또는 **InfluxDB** 사용을 권장.
    *   **정형/비정형 데이터 (뉴스, 기업 정보):** 범용성이 높은 **PostgreSQL** 이나 문서 기반의 **MongoDB** 사용.
*   **데이터 스키마 (예시: PostgreSQL):**
    *   `stocks` (종목 정보): `id`, `ticker_symbol`, `stock_name`, `market` (KOSPI, NASDAQ)
    *   `stock_prices` (주가): `stock_id`, `timestamp`, `open`, `high`, `low`, `close`, `volume`
    *   `news_articles` (뉴스): `id`, `stock_id` (optional), `title`, `content`, `url`, `published_at`

### 3.3. AI 분석 및 결정 계층 (AI Agent Design)

*   **Feature Engineering:**
    *   **기술적 지표:** 이동평균(MA), RSI, MACD, 볼린저 밴드 등 표준 기술적 분석 지표를 계산하여 피처로 활용.
    *   **뉴스 분석:**
        *   **감성 분석 (Sentiment Analysis):** KoBERT (국내), FinBERT (미국) 등 금융 도메인에 특화된 언어 모델을 사용하여 뉴스 기사의 긍정/부정/중립 톤을 수치화.
        *   **핵심 개체명 인식 (Named Entity Recognition):** 뉴스 본문에서 언급되는 기업, 인물, 제품 등을 추출하여 연관 관계 분석.
        *   **토픽 모델링 (Topic Modeling):** LDA 등을 활용하여 시장의 주요 관심사를 파악.

*   **AI 모델:**
    *   **초기 모델 (Rule-Based):** "특정 종목의 긍정 뉴스 발생 & 주가가 20일 이동평균선 돌파 시 매수" 와 같이 간단한 규칙 기반으로 시작하여 빠르게 프로토타입을 검증.
    *   **고급 모델 (Machine Learning):**
        *   **분류 모델 (XGBoost, LightGBM):** 가공된 피처들을 기반으로 N분 후 주가의 상승/하락을 예측하는 분류 문제로 접근.
        *   **시계열 예측 모델 (LSTM, Transformer):** 주가 패턴 자체를 학습하여 미래 주가를 예측. 뉴스 감성 점수 등을 추가 입력으로 활용 가능.

*   **결정 논리 (Decision Logic):**
    *   AI 모델의 예측 결과 (e.g., "상승 확률 75%")를 입력받아 최종 매수/매도 신호를 생성.
    *   과매수/과매도 구간 등 시장 상황을 고려한 필터링 로직 추가.

---

## 4. 기술 스택 (Technology Stack)

*   **언어:** Python 3.9+
*   **핵심 라이브러리:**
    *   **데이터 수집:** `requests`, `beautifulsoup4`, `scrapy`, `yfinance`, `pykrx`
    *   **데이터 분석/처리:** `pandas`, `numpy`, `ta` (기술적 분석)
    *   **AI/ML:** `scikit-learn`, `tensorflow` or `pytorch`, `transformers` (Hugging Face)
    *   **데이터베이스 연동:** `psycopg2-binary` (PostgreSQL), `pymongo` (MongoDB)
*   **워크플로우 자동화:** `APScheduler` (주기적 작업 실행), `Celery` (비동기 작업 큐)

---

## 5. 단계별 이행 계획 (Roadmap)

### Phase 1: MVP (Minimum Viable Product) - (1~3개월)

*   **목표:** 핵심 데이터 수집 및 간단한 분석/알림 기능 구현.
*   **내용:**
    1.  국내/미국 각 5~10개 주요 종목에 대한 주가/뉴스 데이터 수집기 개발.
    2.  데이터를 로컬 파일(CSV) 또는 SQLite에 저장.
    3.  간단한 뉴스 감성 분석 (긍정/부정 키워드 매칭) 및 기술적 지표 계산.
    4.  규칙 기반(Rule-Based) AI 에이전트 구현 (e.g., 텔레그램으로 매매 신호 알림).
    5.  **실제 주문은 실행하지 않음 (Paper Trading)**.

### Phase 2: 고도화 및 백테스팅 - (3~6개월)

*   **목표:** AI 모델 도입 및 신뢰성 검증.
*   **내용:**
    1.  데이터베이스 시스템(PostgreSQL/TimescaleDB) 도입.
    2.  수집 대상 종목 확대.
    3.  머신러닝(XGBoost, LSTM 등) 모델 개발 및 학습 파이프라인 구축.
    4.  과거 데이터를 이용한 **백테스팅(Backtesting) 시스템**을 구축하여 전략의 수익률 및 안정성 검증.

### Phase 3: 실전 투자 연동 - (6개월 이후)

*   **목표:** 검증된 전략을 소액으로 실제 시장에 적용.
*   **내용:**
    1.  증권사 API 연동을 통한 주문 실행 모듈 개발.
    2.  포지션 관리, 손절매 등 리스크 관리 모듈 강화.
    3.  전체 시스템의 운영 현황을 모니터링할 수 있는 대시보드 구축.
    4.  **소액으로 실제 투자를 시작**하며 시스템 안정성 및 수익성 지속적 검증/개선.

---

## 6. 리스크 관리 (Risk Management)

자동화 트레이딩 시스템은 상당한 리스크를 내포하므로, 아래와 같은 장치가 반드시 필요합니다.

1.  **최대 투자 비중 제한:** 전체 자산 대비 단일 종목 및 총 투자 비중을 제한.
2.  **손절매 (Stop-Loss) 원칙:** 매수 가격 대비 일정 비율 이상 하락 시 자동으로 매도하여 손실을 제한.
3.  **시스템 오류 방지:** API 응답 오류, 네트워크 문제 등 기술적 결함 발생 시 모든 주문을 중단하고 관리자에게 즉시 알리는 `Circuit Breaker` 패턴 적용.
4.  **백테스팅:** 어떠한 전략도 충분한 기간의 백테스팅을 통해 검증되기 전까지는 실전 투자에 적용하지 않아야 합니다.
5.  **점진적 확대:** 초기에는 소액으로 시작하여 시스템의 안정성과 전략의 유효성을 충분히 검증한 후 점진적으로 투자금을 늘려야 합니다.
