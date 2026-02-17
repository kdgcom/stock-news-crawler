# Phase 1 MVP 구현 문서 (국내/미국 주식 뉴스-시세 기반)

## 1. 목적

Phase 1의 목표는 "수익 극대화"가 아니라 다음 2가지를 검증하는 것이다.

1. 실시간 뉴스/시세 데이터가 안정적으로 수집되고 정합하게 저장되는가
2. 간단한 규칙 기반 신호로도 재현 가능한 의사결정 파이프라인이 동작하는가

즉, Phase 1은 모델 고도화 이전의 `데이터 + 파이프라인 안정화 단계`다.

---

## 2. 범위 (In Scope)

- 시장: `KRX`, `NYSE/NASDAQ`
- 데이터:
  - 뉴스 원문/헤드라인 수집
  - 1분봉 OHLCV + spread(가능 시)
- 처리:
  - 뉴스 정규화(event_id, symbol, market, language)
  - 중복 제거(upsert)
  - 규칙 기반 event_type/sentiment 점수화
- 의사결정:
  - BUY/SELL/HOLD 규칙 엔진
  - 기본 리스크 게이트(최대 포지션/일손실/스프레드 제한)
- 실행:
  - 실제 주문 아님
  - Paper Trading(모의체결)만 수행
- 관측:
  - 의사결정 로그 및 일별 성과 리포트

---

## 3. 비범위 (Out of Scope)

- 실거래 주문 API 연동
- 딥러닝 기반 고급 NLP 모델 파인튜닝
- 포트폴리오 최적화(다자산 공분산 최적화)
- 초단타(Tick 단위) 집행 최적화

---

## 4. 산출물 (Deliverables)

## D1. 데이터 스키마 및 저장 구조

필수 컬렉션/테이블:
- `raw_news_events`
- `enriched_news_events`
- `market_1m_bars`
- `paper_orders`
- `paper_positions`
- `decision_logs`

필수 인덱스:
- `raw_news_events(event_id unique)`
- `enriched_news_events(event_id unique)`
- `market_1m_bars(market, symbol, ts_event)`
- `decision_logs(ts_utc, symbol)`

## D2. 수집 파이프라인

구성:
- `news_collector_kr`
- `news_collector_us`
- `market_data_collector_kr`
- `market_data_collector_us`

요건:
- 스케줄러 기반 주기 실행(예: 10~60초)
- 실패 재시도 + 지수 백오프
- 입력 원문과 정규화 결과를 분리 보관

## D3. 규칙 기반 분석기

출력 필드:
- `event_type`
- `sentiment_score` (-1~1)
- `confidence` (0~1)
- `impact_horizon` (`intraday`/`swing`)

요건:
- 한글/영문 기본 키워드 사전 분리
- headline 우선, body 보정 방식

## D4. 신호 + 리스크 + 모의체결

신호:
- `BUY`, `SELL`, `HOLD`

리스크 게이트:
- 종목당 최대 수량
- 일 누적 손익 하한
- spread 임계치 초과 시 진입 금지

모의체결:
- 체결가: bar close 또는 간단 슬리피지 반영가
- 주문 상태: `created -> filled/rejected`

## D5. 운영 관측

최소 대시보드/리포트:
- 수집 지연(ms)
- 중복률
- 결측률
- 신호 발생 건수(B/S/H)
- 일별 PnL, MDD(간이)

---

## 5. 기능 요구사항 (Functional Requirements)

1. 뉴스 이벤트는 `event_id` 기준 멱등 처리되어야 한다.
2. 동일 이벤트 재수집 시 문서가 중복 삽입되지 않아야 한다.
3. 모든 이벤트는 `market`, `symbol`, `published_at_utc`를 가져야 한다.
4. 분석기는 입력 뉴스마다 1개의 보강 이벤트를 생성해야 한다.
5. 신호 엔진은 보강 이벤트와 시세 상태를 받아 결정을 반환해야 한다.
6. 리스크 게이트는 신호와 포지션 상태를 받아 승인/차단을 반환해야 한다.
7. paper 실행 결과는 `decision_logs`와 `paper_orders`에 남아야 한다.

---

## 6. 비기능 요구사항 (Non-Functional Requirements)

- 안정성: 수집기 단일 실패가 전체 파이프라인 중단으로 전파되지 않아야 한다.
- 추적성: 모든 의사결정은 `reason_code`로 설명 가능해야 한다.
- 시간 정합성: UTC 기준 저장, 지연 모니터링 가능해야 한다.
- 성능(초기 목표):
  - 이벤트 처리 지연 p95 < 5초 (수집 후 저장/분석 완료)
  - 중복 제거 정확도 > 99%

---

## 7. 작업 분해 (WBS)

## W1. 스키마/저장소 정비
- 데이터 모델 정의
- Mongo 인덱스 생성 스크립트
- upsert 유틸 구현

완료 기준:
- 동일 `event_id` 100회 입력 시 레코드 1건 유지 확인

## W2. 수집기 4종 MVP
- KR 뉴스/US 뉴스 수집기
- KR/US 1분봉 수집기
- 공통 정규화 어댑터

완료 기준:
- 24시간 실행 시 프로세스 비정상 종료 0회

## W3. 분석/신호 엔진
- event_type 분류 규칙
- sentiment 점수화
- BUY/SELL/HOLD 로직

완료 기준:
- 샘플 뉴스 세트에서 기대 라벨과 80% 이상 일치(휴리스틱 기준)

## W4. 리스크/모의실행
- 리스크 게이트
- paper 주문/포지션 업데이트
- 체결/거절 로깅

완료 기준:
- 손실 한도 도달 시 신규 진입 100% 차단

## W5. 관측/리포트
- 일별 성과 집계 스크립트
- 기본 모니터링 메트릭 출력

완료 기준:
- 1일치 리포트 자동 생성 + 주요 지표 누락 없음

---

## 8. 수용 기준 (Acceptance Criteria)

다음 조건을 모두 만족하면 Phase 1 완료로 판단한다.

1. 2주 이상 paper 모드 연속 운영 가능
2. 데이터 중복률 1% 미만
3. 수집 결측 알림 및 복구 절차 문서화 완료
4. 의사결정 로그 재현 가능 (특정 거래의 입력/판단/결과 추적 가능)
5. 리스크 룰 위반 거래 0건

---

## 9. 테스트 계획

## 단위 테스트
- event_id 생성 일관성
- sentiment 규칙 함수
- risk gate 룰 함수

## 통합 테스트
- 수집 -> 저장 -> 분석 -> 신호 -> paper 주문 전체 플로우
- 중복 이벤트 재주입 시 멱등 동작

## 회귀 테스트
- 룰 임계치 변경 전/후 신호 분포 비교

---

## 10. 일정 제안 (4~6주)

- 1주차: W1
- 2~3주차: W2
- 4주차: W3
- 5주차: W4
- 6주차: W5 + 안정화

버퍼:
- 소스 차단/HTML 변경 대응 버퍼 20% 확보

---

## 11. 리스크와 대응

- 뉴스 소스 구조 변경:
  - 대응: 파서별 계약 테스트 + fallback 소스 준비
- 종목 매핑 오류:
  - 대응: 수동 검수 큐 + 매핑 사전 버전관리
- 이벤트 시각 불일치:
  - 대응: source timestamp 우선 + ingest timestamp 병행 저장
- 과도한 신호 발생:
  - 대응: confidence 하한/쿨다운/일 최대 주문 수 제한

---

## 12. Phase 2 진입 조건

Phase 1 이후 다음 조건을 만족하면 Phase 2(모델 고도화)로 진행한다.

1. 데이터 품질 지표 안정화(결측/중복/지연)
2. paper 성과의 일관성 확인(특정 구간 편향 아님)
3. 리스크 통제 룰의 운영 신뢰성 확보

즉, Phase 2는 "데이터/운영이 준비된 후" 시작한다.
