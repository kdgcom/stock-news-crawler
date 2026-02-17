# 국내/미국 주식 대상 실시간 뉴스-시세 기반 AI 매매 Agent 설계안

## 1. 목표와 전제

이 문서의 목표는 다음 3가지를 동시에 만족하는 실제 구축 가능한 구조를 제시하는 것이다.

1. 국내(KRX) + 미국(NYSE/NASDAQ) 종목의 뉴스/시세를 실시간에 가깝게 수집한다.
2. 뉴스 이벤트와 가격 반응을 함께 해석해 종목별 매수/매도/관망을 결정한다.
3. 실제 주문 전 단계에서 리스크를 강하게 통제해 "망가지지 않는 시스템"으로 운영한다.

핵심 전제:
- 완전 자동매매를 바로 시작하지 않는다. `신호 품질 검증 -> 모의투자 -> 소액 실거래` 단계로 올라간다.
- 모델 정확도보다 먼저 `데이터 품질`, `체결/리스크 제어`, `장애 복구`를 설계한다.
- 한국/미국 시장의 거래시간, 공시 문화, 언어(한글/영문) 차이를 분리해 설계한다.

---

## 2. 최상위 아키텍처

```text
[Collector Layer]
  - News Collector (KR/US)
  - Market Data Collector (Tick/1m/OHLCV)
  - Corporate Event Collector (공시, 실적, 가이던스, 배당/분할)
        |
        v
[Streaming Bus]
  - Kafka or Redis Streams (event-time 기준)
        |
        v
[Feature & Storage Layer]
  - Raw Data Lake (원문)
  - Processed Feature Store (모델 입력용)
  - Low-latency Cache (최근 N분 상태)
        |
        v
[Inference & Decision Layer]
  - NLP/Event 모델
  - Price Regime/Volatility 모델
  - Signal Fusion + Position Sizing
  - Risk Gate (최종 차단기)
        |
        v
[Execution Layer]
  - KR Broker Adapter
  - US Broker Adapter
  - Order Router + Retry + Slippage Control
        |
        v
[Monitoring & Governance]
  - 실시간 PnL / 노출 / DD
  - 모델 drift / 데이터 결측 / 지연 경보
  - 감사 로그 (왜 매수/매도했는지 설명 가능)
```

권장 기술 스택(현재 Python 코드베이스 기준):
- 수집/처리: `Python + AsyncIO + Celery(or Faust/Bytewax)`
- 버스: `Kafka`(규모 크면) 또는 `Redis Streams`(초기 MVP)
- 저장소:
  - 원문: `S3/MinIO` 스타일 오브젝트 저장
  - 조회/분석: `PostgreSQL/ClickHouse`
  - 캐시: `Redis`
  - 기존 `MongoDB`는 뉴스 원문 아카이브 용도로 유지 가능
- 모델: `PyTorch/LightGBM + HuggingFace`
- 오케스트레이션: `Airflow/Prefect`
- 모니터링: `Prometheus + Grafana + Alertmanager`

---

## 3. 데이터 설계 (가장 중요)

## 3.1 뉴스 데이터 스키마 (정규화)

최소 필드:
- `event_id`: 소스+url+timestamp 기반 해시 (중복 제거 핵심)
- `market`: `KR` or `US`
- `symbol`: 표준 티커 (KR: 6자리, US: 알파벳)
- `published_at_utc`
- `headline`, `body`, `language`
- `source_name`, `source_type` (언론/공시/블로그/SNS)
- `event_type` (실적, 가이던스, M&A, 규제, 제품출시, 소송, 매크로 등)
- `sentiment_score` (-1~1)
- `novelty_score` (기존 뉴스 대비 새로운 정보인지)
- `reliability_score` (소스 신뢰도)

핵심 규칙:
- 모든 시간은 UTC 저장, 화면에서만 현지시간으로 변환.
- 원문 보관 + 전처리 텍스트 분리 저장.
- 동일 뉴스의 재송출(복붙 기사)은 군집화해 과대반응을 막는다.

## 3.2 시세/체결 데이터 스키마

- `symbol`, `market`, `ts_event`, `open/high/low/close/volume`
- `bid/ask spread`, `microprice`, `volatility_1m/5m`
- `halt_flag`, `auction_flag` (시장상태)

핵심 규칙:
- event-time과 ingest-time을 모두 저장해 지연(latency) 분석.
- 결측 구간은 명시적으로 `missing` 플래그를 남기고 추정값으로 덮지 않는다.

## 3.3 기업 매핑(Master Data)

- 한국/미국 종목 코드 맵 테이블을 별도 관리.
- 동음이의 기업명(예: "애플" 일반명사 vs Apple Inc.) disambiguation 규칙 필요.
- 상장폐지, 티커변경, 액면분할 이력 테이블은 필수.

---

## 4. 모델 계층 설계

단일 "거대 모델" 하나로 끝내지 말고, 역할별 소형 모델 조합을 권장한다.

## 4.1 NLP/Event 모델

출력:
- `event_type`
- `event_sentiment`
- `impact_horizon` (초단기/일중/스윙)
- `confidence`

방법:
- 한글/영문 분리 모델 또는 멀티링구얼 모델.
- 라벨 부족 초기에는 규칙+약지도(weak supervision)로 시작.
- 실적/가이던스 같은 구조적 이벤트는 룰 기반 파서와 결합.

## 4.2 가격 체제(Regime) 모델

출력:
- `trend_state`: 상승/하락/횡보
- `vol_state`: 저/중/고변동성
- `liquidity_state`: 체결 가능성

방법:
- HMM, Gradient Boosting, 또는 간단한 state classifier.
- 뉴스 신호가 좋아도 변동성 과열 구간이면 진입 크기 축소.

## 4.3 신호 융합(Fusion) 모델

입력:
- 뉴스 임베딩/점수 + 시세 파생변수 + 시장 체제

출력:
- `score_buy`, `score_sell`, `expected_return`, `risk_penalty`

방법:
- 초기: `LightGBM/XGBoost` (해석성과 학습 속도 우수)
- 고도화: 시계열 Transformer/TFT

주의:
- 뉴스 공개 직후의 look-ahead leakage를 엄격히 차단.
- 백테스트 데이터셋에서 "기사 게시 시각 정합성"이 가장 큰 함정.

---

## 5. 의사결정 Agent 로직

## 5.1 의사결정 단계

1. 이벤트 수신
2. 종목 매핑/중복 제거
3. NLP/Event 점수 계산
4. 시세/체제 피처 결합
5. 매수/매도 확률 계산
6. 리스크 게이트 통과 여부 평가
7. 주문 생성 또는 관망

## 5.2 의사결정 규칙 예시

```python
if confidence < C_MIN:
    action = "HOLD"
elif risk_gate_blocked:
    action = "HOLD"
elif score_buy - score_sell > TH_BUY:
    action = "BUY"
elif score_sell - score_buy > TH_SELL:
    action = "SELL"
else:
    action = "HOLD"
```

포지션 크기 예시:

`position_size = base_risk_budget * confidence * liquidity_factor / volatility_factor`

즉, 같은 매수 신호라도
- 신뢰도 높고
- 유동성 좋고
- 변동성 과열이 아니면
사이즈를 키운다.

---

## 6. 리스크 관리(모델보다 우선)

필수 가드레일:
- 종목당 최대 노출 (예: NAV의 x%)
- 섹터당 최대 노출
- 일 손실 한도(daily stop)
- 연속 손실 횟수 제한(쿨다운)
- 이벤트 직후 n초 주문 금지(뉴스 오인식 완충)
- 스프레드/슬리피지 임계치 초과 시 진입 금지
- 거래소 상태 이상(서킷브레이커/거래정지) 시 전면 중지

실무 핵심:
- "신호 생성"과 "주문 실행" 사이에 독립 리스크 프로세스를 둔다.
- 장애 시 기본값은 always-safe (`no new position`).

---

## 7. 한국/미국 시장 분리 설계 포인트

## 7.1 거래시간/세션
- KR: 정규장 중심, 동시호가/시간외 처리 규칙 필요.
- US: 프리/정규/애프터 세션 분리; 세션별 유동성 모델 따로 관리.

## 7.2 언어와 뉴스 소스
- KR: 한글 형태소 이슈(기업명, 조사, 띄어쓰기) 대응.
- US: 영문 속보 빈도 높아 headline velocity feature 유용.

## 7.3 실행 어댑터
- 브로커 API는 국가별로 완전 분리 구현.
- 공통 인터페이스 예시: `place_order()`, `cancel_order()`, `get_position()`
- 내부 표준 주문 객체로 변환 후 라우팅.

---

## 8. 검증 프레임워크 (백테스트 + 워크포워드)

백테스트 최소 요구:
- 이벤트 시각 기준 체결 가능 가격으로 시뮬레이션
- 수수료/세금/슬리피지 반영
- 거래 불가 구간(정지, 호가 공백) 반영

평가 지표:
- 수익: CAGR, Sharpe, Sortino
- 손실: MDD, CVaR, Tail loss
- 운영: Hit ratio, Turnover, Avg holding time
- 안정성: 월별 성과 분산, Regime별 성능

검증 절차:
1. In-sample 학습
2. Out-of-sample 테스트
3. Walk-forward 재학습
4. Paper trading (최소 4~8주)
5. 소액 실거래

---

## 9. 운영/MLOps

필수 대시보드:
- 데이터 지연(뉴스 수집 지연, 시세 지연)
- 피처 결측률
- 모델 confidence 분포 변화(drift)
- 주문 실패율/재시도율
- 실현손익/미실현손익/노출

배포 전략:
- `champion/challenger` 구조로 모델 교체
- 새 모델은 먼저 paper 계정에서 shadow mode 실행
- 롤백은 1분 이내 가능한 절차 자동화

---

## 10. 단계별 구축 로드맵

## Phase 1 (MVP, 4~6주)
- KR/US 뉴스 + 1분봉 시세 수집 파이프라인
- 표준 스키마 저장 + 중복 제거
- 단순 sentiment + rule-based 매매 신호
- 모의투자 리플레이 엔진

목표: "데이터 정합성과 파이프라인 안정성" 확보

## Phase 2 (8~12주)
- 이벤트 분류기 + 체제 모델 + fusion 모델 도입
- 리스크 게이트 고도화
- walk-forward 백테스트 자동화

목표: "신호 품질" 개선

## Phase 3 (12주+)
- 브로커 연동 실거래(소액)
- 시장별(한/미) 전략 분화
- 포트폴리오 레벨 최적화

목표: "운영 가능한 자동화" 완성

---

## 11. 현재 저장소(stock-news-crawler)에 맞춘 구체 액션

현재 구조는 뉴스 크롤링 + Mongo 저장의 초기 골격이다. 아래 순서로 확장하면 된다.

1. `src/scraper.py`
- 사이트별 파서가 아닌 "커넥터 + 정규화" 구조로 분리
- `market`, `symbol`, `published_at_utc`, `source_type` 필드 추가

2. `src/models.py`
- `NewsArticle`를 `RawNewsEvent` + `EnrichedNewsEvent`로 분리
- `event_id`, `language`, `event_type`, `sentiment_score`, `confidence` 추가

3. `src/news_analyzer.py`
- `analyze_price_impact` 단일 함수 대신
  - `classify_event_type`
  - `score_sentiment`
  - `estimate_horizon`
  로 분해

4. `src/data_manager.py`
- upsert(중복 키: `event_id`) 지원
- 조회 API에 시간 인덱스/종목 인덱스 최적화

5. 신규 모듈 제안
- `src/market_data_collector.py`
- `src/signal_engine.py`
- `src/risk_engine.py`
- `src/execution_router.py`
- `src/backtest/`

---

## 12. 현실적인 결론

잘 작동하는 AI 매매 Agent의 핵심은 "모델이 똑똑함"보다 다음 4가지다.

1. 신뢰 가능한 실시간 데이터
2. 이벤트 시각 정합성을 지킨 검증 체계
3. 보수적인 리스크 게이트
4. 장애 시 자동으로 멈추는 운영 구조

즉, 뉴스/시세/모델/주문을 하나의 파이프라인으로 보고, 특히 `리스크 엔진을 최종 의사결정권자`로 두는 구조가 국내/미국 동시 운용에서 가장 실전적이다.

---

## 부록 A. 초기 의사결정 기준(샘플)

- `BUY` 조건:
  - `score_buy >= 0.72`
  - `confidence >= 0.65`
  - `spread_pct <= 0.15%`
  - `volatility_state != EXTREME`
- `SELL` 조건:
  - `score_sell >= 0.72` 또는 `stop-loss/hard risk`
- `HOLD`:
  - 위 조건 미충족 전부

위 임계값은 고정값으로 시작하고, walk-forward로 월 단위 재추정한다.

## 부록 B. 최소 로그 스키마

- `decision_id`, `ts_utc`, `symbol`, `market`
- `input_features_hash`
- `model_version`
- `decision` (BUY/SELL/HOLD)
- `reason_codes` (예: `LOW_CONFIDENCE`, `RISK_BLOCK`, `HIGH_SPREAD`)
- `order_result` (sent/rejected/filled/partial)

이 로그가 있어야 나중에 "왜 이 거래를 했는가"를 재현할 수 있다.
