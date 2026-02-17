# 알고리즘 방식 분석: 수치 기반 vs Agent vs Hybrid

## 1. 현재 설계 진단 (`md/plan_detail` 기준)
현재 구조는 이미 매우 체계적이지만, 본질적으로는 **수치 기반 플러그인 엔진**이다.

- `06-analysis-engine.md`: `BaseAlgorithm` + `AlgorithmRouter` + `EnsembleRunner` 중심
- `weighted_vote`, `buy/sell threshold`, `min_agreement` 등 점수 합산형 의사결정
- `07-risk-management.md`: 3단계 리스크 게이트(하드리밋/동적/킬스위치)
- `08-execution.md`: 리스크 통과 후 실행(Paper/실거래)

즉, "여러 알고리즘"은 있으나, 역할이 분리된 **자율 Agent 간 협업/검증 프로토콜**은 아직 없다.

---

## 2. 방식 A: 기존 수치 기반(Score Engine) 정식 정의

### 설계 요약
- 입력: 시세/뉴스/파생지표
- 처리: 개별 알고리즘이 `score (-1~1), confidence` 산출
- 통합: 가중합 + 임계치로 BUY/SELL/HOLD
- 보호: 리스크 게이트가 최종 차단

### 강점
- 빠르고 비용이 낮음
- 재현성과 디버깅이 쉬움
- 규칙 변경/백테스트 자동화가 용이

### 한계
- 뉴스 맥락 해석(반어, 복합 이벤트, 서사적 변화)에 약함
- 시장 구조 급변 시 규칙 경직성 발생

---

## 3. 방식 B: Agent 기반 설계 (신규 제안)

## 3.1 핵심 아이디어
기존 "단일 점수 합산"을 "역할 분리된 에이전트들의 합의"로 확장한다.

## 3.2 권장 Agent 구성
1. `NewsAgent`
- 뉴스/공시/이벤트를 해석하고 `event thesis` 생성
- 출력: `direction`, `impact_horizon`, `confidence`, `key_risks`

2. `TechnicalAgent`
- RSI/MACD/추세/볼륨 구조를 해석
- 출력: `trend_state`, `entry_timing`, `invalidations`

3. `RegimeAgent`
- 변동성/유동성/리스크 온오프 상태 판정
- 출력: `regime`, `risk_multiplier`

4. `PortfolioAgent`
- 포지션 사이징, 섹터 편중, 기존 보유 포지션 충돌 확인
- 출력: `target_size`, `hedge_or_reduce`

5. `RiskGuardianAgent` (최종 거부권)
- 기존 `07-risk-management` 룰을 Agent 인터페이스로 감싼 수문장
- 출력: `PASS/BLOCK`, `blocker_reason`

6. `ExecutionAgent`
- 주문 타입/분할 체결/재시도 전략 제안
- 출력: `order_plan`

## 3.3 오케스트레이션 프로토콜
- Step 1. `Coordinator`가 컨텍스트 생성 (`AlgorithmContext` 확장)
- Step 2. `News/Technical/Regime` 병렬 실행
- Step 3. `PortfolioAgent`가 통합 주문 초안 생성
- Step 4. `RiskGuardianAgent`가 승인/차단
- Step 5. 승인 시 `ExecutionAgent` 실행, 전 과정 `decision_logs` 기록

## 3.4 Agent 출력 계약(권장)
```json
{
  "agent": "news_agent",
  "symbol": "AAPL",
  "stance": "BUY|SELL|HOLD",
  "score": 0.62,
  "confidence": 0.74,
  "reason_codes": ["EARNINGS_BEAT", "GUIDANCE_UP"],
  "evidence": ["event_id:...", "indicator:RSI=31"],
  "risk_flags": ["HIGH_VOLATILITY"],
  "ttl_seconds": 300
}
```

## 3.5 운영 원칙
- Agent 결론도 반드시 수치화(`score/confidence`)하여 기존 로깅 체계와 결합
- 예산 제한: 일 LLM 호출 횟수/토큰 상한 초과 시 자동 `수치 기반 모드`로 폴백
- 무응답/지연 시 기본값은 `HOLD`

---

## 4. 방식 C: Hybrid (권장)

## 4.1 핵심 전략
**수치 기반을 기본 엔진**으로 유지하고, Agent를 "고난도 판단 구간"에만 선택적으로 호출한다.

## 4.2 Hybrid 의사결정 규칙
1. 1차 필터: 기존 수치 엔진으로 전 종목 스코어링
2. Agent 호출 조건:
- 임계치 근처 애매한 케이스 (`|score|`가 buy/sell threshold 근접)
- 고영향 이벤트(실적/규제/소송/M&A)
- 알고리즘 간 상충(예: 뉴스 강세 vs 기술 약세)
3. 2차 검증: Agent 결론으로 점수 보정
4. 최종: Risk Gate 통과 시 실행

## 4.3 Hybrid 통합 수식(예시)
- `final_score = alpha * numeric_score + (1 - alpha) * agent_score`
- 기본 `alpha = 0.7`
- 고변동/뉴스 폭증 구간은 `alpha`를 0.4~0.6으로 자동 하향

## 4.4 적용 포인트 (현재 설계와 연결)
- `06-analysis-engine.md`: `AgentOverlayRunner` 추가
- `07-risk-management.md`: `RiskGuardianAgent`는 기존 룰 재사용(로직 동일)
- `08-execution.md`: 실행부 변경 최소화, 입력 스키마만 확장

---

## 5. 방식별 장단점 비교

| 방식 | 장점 | 단점 | 비용/운영 난이도 | 설명가능성/감사 | 적합 단계 |
|---|---|---|---|---|---|
| 수치 기반 | 빠름, 저비용, 백테스트 용이, 재현성 높음 | 정성 해석 약함, 구조 변화 대응 둔감 | 낮음 | 매우 높음(규칙 추적 쉬움) | MVP~초기 상용 |
| Agent 기반 | 복합 이벤트 해석 강함, 컨텍스트 추론 우수, 적응성 높음 | 지연/비용 증가, 프롬프트/품질 관리 필요, 비결정성 | 높음 | 중간(로그 설계 잘하면 개선 가능) | 고도화 이후 |
| Hybrid | 비용-성능 균형, 핵심 구간만 Agent 활용, 실패 시 폴백 가능 | 아키텍처 복잡도 증가, 가중치/호출조건 튜닝 필요 | 중간 | 높음(수치+Agent 근거 동시 기록) | **현재 프로젝트 최적** |

---

## 6. 권장 결론

현 프로젝트는 이미 수치 기반 엔진과 리스크 체계가 견고하므로, **전면 Agent 전환보다 Hybrid 도입**이 가장 현실적이다.

- 단기(즉시): 기존 수치 기반 유지
- 중기: Agent Overlay를 고영향 이벤트 구간에만 적용
- 장기: Agent 성능/비용/지연이 검증되면 적용 범위를 확대

즉, "기본은 결정론적 수치 엔진, 예외와 복잡성은 Agent" 전략이 5년 운영에 가장 안전하다.
