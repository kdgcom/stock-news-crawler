# Codex 통합 신규 기획안 (KR/US 뉴스·시세 기반 투자 의사결정 시스템)

## 1. 기획 원칙
- 데이터 품질이 모델 정확도보다 우선이다.
- 실거래 전, 반드시 `백테스트 → 워크포워드 → 페이퍼 트레이딩`을 통과한다.
- 리스크 엔진이 최종 의사결정권자다.
- 초기에는 단순하고, 운영하면서 고도화한다.

## 2. 목표
1. 한국/미국 종목의 뉴스·시세·공시를 표준화 수집한다.
2. 이벤트/감성/기술/체제 신호를 결합해 `BUY/SELL/HOLD`를 산출한다.
3. 하드 리밋과 킬스위치를 통해 손실 상한을 강제한다.
4. 12주 내 운영 가능한 MVP를 구축하고, 이후 실전 전환한다.

## 3. 시스템 아키텍처 (통합)
- **Collection Layer**: KR/US 뉴스, 1분봉 시세, DART/SEC 공시 수집
- **Event Bus Layer**: Redis Streams(초기), 필요 시 Kafka 전환
- **Storage Layer**: MongoDB(원문/이벤트), TimescaleDB(시계열), Redis(저지연 캐시)
- **Analysis Layer**:
  - Sentiment/Event 분석(LLM+룰)
  - Technical/Regime 분석(RSI, MACD, 변동성 상태)
  - Fusion 모델(LightGBM/XGBoost 시작)
- **Decision Layer**: Signal Aggregator + Risk Gate
- **Execution Layer**: Paper Executor(초기), Broker Adapter(후기)
- **Ops Layer**: 모니터링, 알림, 감사 로그, 장애복구

## 4. 데이터 표준

## 4.1 뉴스 이벤트 스키마
- `event_id`(source+url+published_at 해시, unique)
- `market`, `symbol`, `published_at_utc`, `ingested_at_utc`
- `title`, `body`, `source_name`, `source_type`
- `event_type`, `sentiment_score`, `confidence`, `reliability_score`

## 4.2 시세 스키마
- `market`, `symbol`, `ts_event`, `open/high/low/close/volume`
- `spread`, `volatility_1m/5m`, `halt_flag`

## 4.3 핵심 품질 규칙
- UTC 저장 고정
- `event_id` 멱등 upsert
- 결측/지연/중복률을 메트릭으로 관리
- 동일 기사 재송출 군집화

## 5. 의사결정 구조

## 5.1 다층 신호
- `S_news`: 이벤트 유형 + 감성 점수
- `S_tech`: 기술적 지표 점수
- `S_regime`: 시장 체제(추세/변동성/유동성)
- `S_fusion`: 최종 점수

예시:
`S_fusion = w1*S_news + w2*S_tech + w3*S_regime`

## 5.2 행동 규칙
- 신뢰도/품질 기준 미달 시 `HOLD`
- 점수 임계치 충족 시 `BUY/SELL`
- 리스크 게이트 차단 시 무조건 `HOLD`

## 5.3 포지션 사이징
`size = risk_budget * confidence * liquidity_factor / volatility_factor`

## 6. 리스크/컴플라이언스 체계

## 6.1 하드 리밋
- 종목당 최대 비중
- 일손실/주손실/MDD 상한
- 일 최대 주문 횟수
- 최소 현금 비율

## 6.2 킬스위치 자동 조건
- 일손실 한도 초과
- API 연속 실패
- 데이터 지연/결측 급증
- 비정상 주문 패턴 감지

## 6.3 감사 추적
- 모든 결정에 `reason_code`, 입력 피처 해시, 모델 버전 기록
- `decision -> risk check -> order result` 전 과정 재현 가능해야 함

## 7. 단계별 실행 로드맵

## Phase 1 (1~4주): 데이터·스키마 안정화
- KR/US 뉴스 + 1분봉 수집기
- 표준 스키마, upsert, 인덱스
- 중복/결측/지연 메트릭 대시보드

완료 기준:
- 중복 입력 100회 시 저장 1건 유지
- 주요 파이프라인 24시간 무중단

## Phase 2 (5~8주): 규칙 기반 신호 + 페이퍼 실행
- 이벤트/감성 규칙 엔진
- 기술 지표 엔진
- 리스크 게이트 + 페이퍼 체결

완료 기준:
- 리스크 위반 거래 0건
- 의사결정 로그 100% 추적 가능

## Phase 3 (9~12주): ML Fusion + 검증 자동화
- LightGBM/XGBoost fusion
- 백테스트 + 워크포워드 자동화
- 임계치/가중치 튜닝

완료 기준:
- OOS 성능 리포트 자동 생성
- 페이퍼 4주 연속 안정 운영

## Phase 4 (13주+): 소액 실거래 전환
- 브로커 어댑터 연동
- 소액 자금 단계적 증액
- 챔피언/챌린저 모델 운용

완료 기준:
- 운영 가동률 99%+
- 킬스위치/복구 훈련 통과

## 8. MVP 기술 스택
- Python 3.11+
- 수집: requests, bs4, asyncio
- 처리/모델: pandas, ta, scikit-learn, lightgbm
- 저장: MongoDB, TimescaleDB, Redis
- 오케스트레이션: APScheduler(초기) → Celery/Prefect(확장)
- 관측: Prometheus + Grafana + Slack/Telegram 알림

## 9. 성공 기준 (정량)
- 데이터 중복률 < 1%
- 이벤트 처리 지연 p95 < 5초
- 리스크 룰 위반 거래 0건
- decision log 누락 0건
- 페이퍼 운영 2주 이상 무중단(Phase 2), 4주 이상 안정(Phase 3)

## 10. 핵심 차별점
- Gemini의 **간결한 계층 구조**
- GPT의 **실행 체크리스트와 검증 중심 MVP 설계**
- Claude의 **운영·리스크·컴플라이언스 완성도**

을 결합해, “빠르게 만들되 쉽게 망가지지 않는” 투자 의사결정 시스템을 목표로 한다.
