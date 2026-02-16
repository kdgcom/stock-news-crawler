# Phase 1 MVP 실행표 (체크리스트)

## 1. 운영 기준

- 기준 문서: `md/gpt/phase1-mvp-implementation.md`
- 운영 단위: 주간 스프린트(1주)
- 상태 값: `TODO`, `DOING`, `BLOCKED`, `DONE`
- 우선순위: `P0`(필수), `P1`(중요), `P2`(개선)

---

## 2. 역할 정의

- `PM/Owner`: 일정/범위/의사결정 총괄
- `Data Eng`: 수집/저장/스키마/인덱스
- `ML Eng`: 분석기/신호 엔진
- `Quant/Risk`: 리스크 룰/검증
- `DevOps`: 배포/모니터링/알람
- `QA`: 테스트/회귀 검증

---

## 3. 마일스톤 실행표

## M1. 저장소/스키마 정비 (Week 1, P0)

| ID | 작업 | 담당 | 우선순위 | 상태 | 산출물 | 완료 기준 |
|---|---|---|---|---|---|---|
| M1-01 | Raw/Enriched 이벤트 스키마 확정 | Data Eng | P0 | TODO | 스키마 문서 | 필수 필드 100% 정의 |
| M1-02 | Mongo 컬렉션/인덱스 생성 스크립트 작성 | Data Eng | P0 | TODO | init 스크립트 | unique/index 정상 생성 |
| M1-03 | event_id 생성 규칙 정의(멱등) | Data Eng | P0 | TODO | 규칙 문서 + 함수 | 동일 입력 동일 ID 보장 |
| M1-04 | upsert 저장 경로 구현 | Data Eng | P0 | TODO | 저장 모듈 | 중복 100회 입력 시 1건 유지 |
| M1-05 | 스키마 검증 유틸 추가 | QA | P1 | TODO | validator | 누락 필드 탐지 가능 |

체크리스트:
- [ ] event_id 충돌 테스트 완료
- [ ] UTC 저장 규칙 확인
- [ ] 인덱스 성능(기본 조회) 점검

---

## M2. 수집기 MVP 4종 (Week 2-3, P0)

| ID | 작업 | 담당 | 우선순위 | 상태 | 산출물 | 완료 기준 |
|---|---|---|---|---|---|---|
| M2-01 | KR 뉴스 수집기 구현 | Data Eng | P0 | TODO | collector_kr_news | 1시간 무중단 수집 |
| M2-02 | US 뉴스 수집기 구현 | Data Eng | P0 | TODO | collector_us_news | 1시간 무중단 수집 |
| M2-03 | KR 1분봉 수집기 구현 | Data Eng | P0 | TODO | collector_kr_price | 결측 탐지 가능 |
| M2-04 | US 1분봉 수집기 구현 | Data Eng | P0 | TODO | collector_us_price | 결측 탐지 가능 |
| M2-05 | 공통 정규화 어댑터 적용 | Data Eng | P0 | TODO | normalize module | market/symbol/time 표준화 |
| M2-06 | 재시도/백오프/실패로그 추가 | DevOps | P1 | TODO | retry policy | 실패 후 자동 재시도 |

체크리스트:
- [ ] source timestamp + ingest timestamp 동시 저장
- [ ] 뉴스 중복률 지표 수집
- [ ] 24시간 burn-in 실행 계획 수립

---

## M3. 분석/신호 엔진 (Week 4, P0)

| ID | 작업 | 담당 | 우선순위 | 상태 | 산출물 | 완료 기준 |
|---|---|---|---|---|---|---|
| M3-01 | 이벤트 타입 규칙 사전 작성(KR/US) | ML Eng | P0 | TODO | ruleset v1 | 주요 이벤트 커버 |
| M3-02 | 감성 점수 함수 구현 | ML Eng | P0 | TODO | sentiment scorer | 점수 범위 -1~1 보장 |
| M3-03 | confidence 산정 규칙 구현 | ML Eng | P1 | TODO | confidence rules | 낮은 신뢰도 차단 가능 |
| M3-04 | BUY/SELL/HOLD 의사결정 함수 구현 | ML Eng | P0 | TODO | signal engine | deterministic 결과 |
| M3-05 | reason_code 로깅 추가 | QA | P1 | TODO | decision log format | 재현 가능한 로그 |

체크리스트:
- [ ] KR/US 키워드 사전 분리
- [ ] 샘플 세트 기준 라벨 일치율 점검
- [ ] 신호 분포(과다신호 여부) 검토

---

## M4. 리스크 게이트 + 모의체결 (Week 5, P0)

| ID | 작업 | 담당 | 우선순위 | 상태 | 산출물 | 완료 기준 |
|---|---|---|---|---|---|---|
| M4-01 | 종목당 최대 포지션 룰 구현 | Quant/Risk | P0 | TODO | risk rule #1 | 한도 초과 진입 차단 |
| M4-02 | 일손실 한도 룰 구현 | Quant/Risk | P0 | TODO | risk rule #2 | 하한 도달 시 신규진입 차단 |
| M4-03 | spread 기반 진입 차단 룰 구현 | Quant/Risk | P0 | TODO | risk rule #3 | 임계치 초과 차단 |
| M4-04 | paper 주문/체결 상태머신 구현 | ML Eng | P0 | TODO | paper executor | created->filled/rejected |
| M4-05 | 포지션/PnL 집계 구현 | Quant/Risk | P1 | TODO | pnl module | 일별 손익 산출 가능 |

체크리스트:
- [ ] 리스크 위반 거래 0건
- [ ] 거절 사유(reason_code) 100% 기록
- [ ] 손실 한도 동작 시나리오 테스트 완료

---

## M5. 모니터링/리포트/안정화 (Week 6, P0)

| ID | 작업 | 담당 | 우선순위 | 상태 | 산출물 | 완료 기준 |
|---|---|---|---|---|---|---|
| M5-01 | 핵심 메트릭 정의 및 수집 | DevOps | P0 | TODO | metrics spec | 지연/결측/중복/신호/PnL |
| M5-02 | 일일 리포트 자동 생성 | Data Eng | P1 | TODO | daily report job | 매일 자동 산출 |
| M5-03 | 경보 정책(지연/결측/오류) 구성 | DevOps | P1 | TODO | alert policy | 임계치 초과 시 알림 |
| M5-04 | 2주 paper 안정화 운영 | PM/Owner | P0 | TODO | 운영 로그 | 무중단/무치명 오류 |
| M5-05 | Phase 1 종료 리뷰 | PM/Owner | P0 | TODO | review doc | 수용 기준 충족 판단 |

체크리스트:
- [ ] 데이터 결측 알림 동작 확인
- [ ] 일별 보고서 누락 0회
- [ ] 운영 장애 대응 절차 문서화

---

## 4. 공통 Definition of Done (DoD)

각 작업은 아래 조건을 모두 만족해야 `DONE`으로 변경 가능.

1. 코드/설정 반영 완료
2. 로그 또는 테스트로 동작 검증 완료
3. 실패 케이스 처리(예외/재시도/경보) 확인
4. 문서(입력/출력/제약) 업데이트 완료

---

## 5. 주간 운영 템플릿

## Week N 계획
- 목표:
- 핵심 작업:
- 리스크:
- 의사결정 필요 항목:

## Week N 결과
- 완료:
- 미완료:
- 이슈/원인:
- 다음 주 이월 항목:

---

## 6. 위험 신호(Red Flags)

아래 항목이 발생하면 즉시 `BLOCKED`로 전환하고 원인 분석을 우선한다.

- 6시간 이상 수집 중단
- 중복률 급증(기준 대비 2배 이상)
- decision log 누락 발생
- risk gate 우회 거래 발생
- 일별 보고서 누락

---

## 7. Phase 1 종료 체크박스

- [ ] 2주 이상 paper 운영 완료
- [ ] 중복률 1% 미만
- [ ] 리스크 위반 거래 0건
- [ ] 의사결정 재현성 확보(로그 기반)
- [ ] 운영/장애 대응 문서 확정

모든 항목 체크 시 Phase 2로 진입한다.
