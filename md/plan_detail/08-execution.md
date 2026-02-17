# 08. 매매 실행

> Phase 2 - Track C (Paper) → Phase 3 - Track C (실거래) | 소요: Week 8~14+

## 실행 경로

```
Phase 1~2: Paper Trading (가상 체결)
    │
    │ 4주 안정 운영 확인
    ▼
Phase 3: 모의투자 API (증권사 모의)
    │
    │ 1개월 안정 운영 확인
    ▼
Phase 3+: 소액 실거래
    │
    │ 5% → 10% → 30% → 목표 (단계적 증액)
    ▼
운영
```

## Paper Executor (Phase 1~2)

```python
class PaperExecutor:
    """가상 체결기 — 실제 API 호출 없이 시뮬레이션"""

    def execute(self, signal: dict) -> dict:
        # Kill Switch 확인
        if kill_switch.is_active():
            return {"status": "BLOCKED", "reason": "KILL_SWITCH"}

        # 리스크 게이트 통과
        risk_ok, risk_reason = risk_gate.check(signal, self.portfolio)
        if not risk_ok:
            self._log_decision(signal, "BLOCKED", risk_reason)
            return {"status": "BLOCKED", "reason": risk_reason}

        # 가상 체결 (현재가 기준)
        current_price = redis.get(f"price_cache:{signal['symbol']}")
        slippage = current_price * 0.001  # 0.1% 슬리피지 가정

        if signal["decision"] == "BUY":
            fill_price = current_price + slippage
            self._open_position(signal, fill_price)
        elif signal["decision"] == "SELL":
            fill_price = current_price - slippage
            self._close_position(signal, fill_price)

        # 의사결정 로그 기록
        self._log_decision(signal, "FILLED", fill_price)

        return {"status": "FILLED", "price": fill_price}
```

## 포지션 관리

```python
# Redis에 실시간 포지션 유지
# Key: position:{market}:{symbol}
# Value: JSON

{
    "symbol": "005930",
    "market": "KR",
    "quantity": 100,
    "avg_cost": 58200,
    "current_price": 59000,
    "peak_price": 59500,
    "opened_at": "2026-02-15T09:05:00Z",
    "unrealized_pnl": 80000,
    "unrealized_pnl_pct": 0.0137,
    "stop_loss_price": 55290,      # 고정 -5%
    "trailing_stop": 57715,        # 고점 대비 -3%
}

# 장 마감 시 BigQuery positions_daily에 스냅샷
```

## 브로커 어댑터 (Phase 3)

```python
class BaseBroker(ABC):
    """공통 인터페이스"""
    @abstractmethod
    def place_order(self, symbol, side, quantity, order_type) -> dict: ...

    @abstractmethod
    def cancel_order(self, order_id) -> dict: ...

    @abstractmethod
    def get_positions(self) -> list[dict]: ...

    @abstractmethod
    def get_balance(self) -> dict: ...

class KISBroker(BaseBroker):
    """한국투자증권 API"""
    # config.broker.kr 설정 사용

class AlpacaBroker(BaseBroker):
    """Alpaca API"""
    # config.broker.us 설정 사용
```

## 단계적 실거래 전환

| 단계 | 기간 | 자금 비율 | 조건 |
|------|------|----------|------|
| Paper | 4주+ | 0% (가상) | 리스크 위반 0건, 로그 100% |
| 모의투자 | 1개월 | 0% (증권사 모의) | API 연동 안정 |
| 소액 1단계 | 1개월 | 5% | MDD < -10% |
| 소액 2단계 | 1개월 | 10% | 누적 수익 > 0 |
| 확대 | 2개월 | 30% | 샤프 > 1.0 |
| 목표 | 이후 | 설정에 따라 | 지속 모니터링 |

**증액 조건 미충족 시 이전 단계로 롤백.**

## 완료 기준

### Paper Trading (Phase 2)
- [ ] 가상 체결 정상 동작
- [ ] 포지션 추적 (Redis) 정상
- [ ] PnL 계산 정확
- [ ] 2주 연속 무중단 운영
- [ ] 리스크 게이트 우회 거래 0건

### 실거래 (Phase 3)
- [ ] KIS 모의투자 API 연동 성공
- [ ] Alpaca Paper API 연동 성공
- [ ] 주문 → 체결 → 포지션 반영 정상
- [ ] Kill Switch → 미체결 전량 취소 정상
- [ ] `config.broker.*.is_paper = true` 확인 (안전장치)

### LangGraph Sell Workflow (Phase 2+)
- [ ] SellApprovalGraph 정상 동작
- [ ] interrupt → 사용자 승인 → resume 정상 흐름
- [ ] 체크포인트 저장 확인 (서버 재시작 후 resume 가능)
- [ ] 승인 없이 48시간 경과 시 자동 만료 확인
- [ ] 거래 원장(trade_ledger) 자동 기록 확인

---

## Hybrid Update (2026-02-16)

### 보유종목 매도 제안 실행 절차
1. `sell_recommendations` 생성
2. 사용자 UI에서 제안 확인/승인
3. 승인된 항목만 주문 요청 생성
4. Risk Gate 재검증 후 실행

### 실행 정책
- 기본값: `auto_execute_sell = false`
- 사용자 승인 없는 매도 주문 금지
- 부분매도(`REDUCE`)는 목표 비율 기반으로 수량 계산

### Cloud Functions 연동 포인트
- `POST /portfolio/input` 완료 시, 해당 종목에 대한 매도 제안 재계산 트리거
- `POST /recommendations/{id}/approve` 호출 시 주문 파이프라인 진입
## Trade Ledger Update (2026-02-16)

### 거래 기록 원칙
- 매수 체결 시 `trade_ledger(side=BUY)` 기록
- 매도 체결 시 `trade_ledger(side=SELL)` 기록
- 수동 입력 체결도 동일 스키마로 저장

### 매도 실행 전 검증
- 대상 종목 `net_quantity > 0` 확인 필수
- 미보유 종목이면 `NO_OPEN_POSITION`으로 차단
- 과매도 방지: `sell_quantity <= net_quantity`

---

## LangGraph Integration (2026-02-17)

> 매도 제안 → 사용자 승인 → 실행 흐름을 LangGraph의 Human-in-the-loop 패턴으로 구현한다.

### 적용 사유

매도 실행 워크플로우는 다음 특성으로 LangGraph에 적합하다:
1. **Human-in-the-loop**: `interrupt()` / `resume()` 패턴이 "사용자 확인 후 실행" 요건에 정확히 부합
2. **상태 영속**: 승인 대기 중 상태가 체크포인트에 저장되어 서버 재시작해도 유실 없음
3. **타임아웃 관리**: 승인 없이 N시간 경과 시 자동 만료 처리
4. **감사 추적**: 전체 워크플로우 이력이 LangGraph trace로 자동 기록

### SellApprovalState 정의

```python
from typing import TypedDict, Annotated
import operator

class SellApprovalState(TypedDict):
    """매도 승인 워크플로우 상태"""
    # --- 입력 ---
    recommendation_id: str                 # 매도 제안 ID
    symbol: str
    market: str
    action: str                            # "SELL" | "REDUCE"
    target_quantity: int                    # 매도 수량
    target_price: float | None             # 목표가 (없으면 시장가)
    reason: str                            # 매도 사유
    score: float                           # 분석 점수
    confidence: float

    # --- 보유 검증 ---
    net_quantity: int                       # 현재 순보유 수량
    holding_valid: bool                    # net_quantity > 0 확인
    validation_reason: str

    # --- 사용자 승인 ---
    user_notified: bool                    # Telegram 알림 발송 여부
    user_decision: str | None              # "APPROVE" | "REJECT" | "MODIFY" | None (대기중)
    user_modified_quantity: int | None      # MODIFY 시 사용자 지정 수량
    approved_at: str | None

    # --- 리스크 재검증 ---
    risk_recheck_passed: bool | None
    risk_recheck_reason: str | None

    # --- 실행 ---
    execution_result: dict | None          # 체결 결과
    ledger_recorded: bool                  # trade_ledger 기록 여부

    # --- 메타 ---
    created_at: str
    expired: bool                          # 타임아웃 만료 여부
    errors: Annotated[list[str], operator.add]
```

### 그래프 구조

```
  ┌───────────────────────────────────────────────────────────────────┐
  │                   SellApprovalGraph                               │
  │                                                                   │
  │  START ──→ [validate_holding] ──→ [notify_user]                  │
  │                                        │                          │
  │                              ┌─────────┘                          │
  │                              ▼                                    │
  │                     *** interrupt() ***                           │
  │                   사용자 승인 대기 (체크포인트)                       │
  │                              │                                    │
  │                    resume(user_decision)                          │
  │                              ▼                                    │
  │                     [process_decision]                            │
  │                       │          │                                │
  │              APPROVE/MODIFY   REJECT                             │
  │                       │          │                                │
  │                       ▼        END ← (기록만)                     │
  │               [risk_recheck]                                     │
  │                       │                                           │
  │              ┌────────┤                                           │
  │            passed   failed                                       │
  │              │        │                                           │
  │              ▼      END ← (BLOCKED 기록)                          │
  │         [execute_sell]                                            │
  │              │                                                    │
  │              ▼                                                    │
  │         [record_ledger]                                          │
  │              │                                                    │
  │            END                                                    │
  └───────────────────────────────────────────────────────────────────┘
```

### 핵심 노드 구현

#### 1. validate_holding — 보유 검증

```python
def validate_holding(state: SellApprovalState) -> dict:
    """매도 대상 종목의 보유 여부 확인"""
    net_qty = get_net_quantity_from_ledger(state["symbol"], state["market"])

    if net_qty <= 0:
        return {
            "net_quantity": net_qty,
            "holding_valid": False,
            "validation_reason": "NO_OPEN_POSITION",
        }

    if state["target_quantity"] > net_qty:
        return {
            "net_quantity": net_qty,
            "holding_valid": False,
            "validation_reason": f"OVERSELL: target={state['target_quantity']} > held={net_qty}",
        }

    return {
        "net_quantity": net_qty,
        "holding_valid": True,
        "validation_reason": "OK",
    }
```

#### 2. notify_user — Telegram 매도 제안 알림

```python
def notify_user(state: SellApprovalState) -> dict:
    """매도 제안을 사용자에게 Telegram으로 알림"""
    if not state["holding_valid"]:
        # 보유 검증 실패 → 사용자 알림 없이 종료
        return {"user_notified": False}

    message = f"""
🔴 매도 제안 #{state['recommendation_id'][:8]}
종목: {state['symbol']} ({state['market']})
제안: {state['action']} {state['target_quantity']}주
사유: {state['reason']}
신뢰도: {state['confidence']:.0%}
보유: {state['net_quantity']}주

/approve_{state['recommendation_id'][:8]} 승인
/reject_{state['recommendation_id'][:8]} 거부
/modify_{state['recommendation_id'][:8]} 수량변경
"""
    notifier = TelegramNotifier(config)
    notifier.send(message)

    return {"user_notified": True}
```

#### 3. interrupt — 사용자 승인 대기

```python
from langgraph.types import interrupt

def wait_for_approval(state: SellApprovalState) -> dict:
    """사용자 승인을 기다린다 (interrupt)"""
    if not state["holding_valid"]:
        return {"user_decision": "AUTO_REJECT", "expired": False}

    # LangGraph interrupt: 여기서 그래프 실행이 멈추고 체크포인트 저장
    user_input = interrupt(
        {
            "question": f"{state['symbol']} {state['action']} {state['target_quantity']}주 — 승인하시겠습니까?",
            "recommendation_id": state["recommendation_id"],
        }
    )

    # resume() 호출 시 user_input에 사용자 응답이 들어옴
    return {
        "user_decision": user_input.get("decision", "REJECT"),
        "user_modified_quantity": user_input.get("modified_quantity"),
        "approved_at": user_input.get("approved_at"),
    }
```

#### 4. process_decision — 사용자 결정 처리

```python
def process_decision(state: SellApprovalState) -> dict:
    """사용자 결정에 따라 분기"""
    decision = state["user_decision"]

    if decision == "MODIFY" and state.get("user_modified_quantity"):
        # 수량 변경 → target_quantity 업데이트
        new_qty = state["user_modified_quantity"]
        if new_qty > state["net_quantity"]:
            return {"errors": [f"MODIFIED_QTY_EXCEEDS_HOLDING: {new_qty}"]}
        return {"target_quantity": new_qty}

    return {}
```

#### 5. risk_recheck — 승인 시점 리스크 재검증

```python
def risk_recheck(state: SellApprovalState) -> dict:
    """승인 시점의 포트폴리오 상태로 리스크 재검증
    (제안 생성~승인 사이 시간차에 의한 리스크 변화 대응)"""
    signal = {
        "symbol": state["symbol"],
        "market": state["market"],
        "decision": "SELL",
        "quantity": state["target_quantity"],
    }
    portfolio = get_current_portfolio()
    passed, reason = risk_gate.check(signal, portfolio)

    return {
        "risk_recheck_passed": passed,
        "risk_recheck_reason": reason,
    }
```

#### 6. execute_sell — 매도 실행

```python
def execute_sell(state: SellApprovalState) -> dict:
    """승인 + 리스크 통과 → 실제(Paper) 매도 실행"""
    executor = get_executor(config)  # PaperExecutor 또는 BrokerExecutor

    result = executor.execute({
        "symbol": state["symbol"],
        "market": state["market"],
        "decision": "SELL",
        "quantity": state["target_quantity"],
        "price": state.get("target_price"),  # None이면 시장가
    })

    return {"execution_result": result}
```

#### 7. record_ledger — 거래 원장 기록

```python
def record_ledger(state: SellApprovalState) -> dict:
    """체결 결과를 trade_ledger에 기록"""
    result = state["execution_result"]
    if result and result.get("status") == "FILLED":
        insert_trade_ledger({
            "symbol": state["symbol"],
            "market": state["market"],
            "side": "SELL",
            "quantity": state["target_quantity"],
            "price": result["price"],
            "source": "sell_recommendation",
            "recommendation_id": state["recommendation_id"],
        })
        return {"ledger_recorded": True}

    return {"ledger_recorded": False, "errors": ["EXECUTION_NOT_FILLED"]}
```

### 그래프 빌드

```python
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver

def build_sell_approval_graph() -> StateGraph:
    graph = StateGraph(SellApprovalState)

    # 노드 등록
    graph.add_node("validate_holding", validate_holding)
    graph.add_node("notify_user",      notify_user)
    graph.add_node("wait_approval",    wait_for_approval)
    graph.add_node("process_decision", process_decision)
    graph.add_node("risk_recheck",     risk_recheck)
    graph.add_node("execute_sell",     execute_sell)
    graph.add_node("record_ledger",    record_ledger)

    # 엣지
    graph.add_edge(START, "validate_holding")
    graph.add_edge("validate_holding", "notify_user")
    graph.add_edge("notify_user", "wait_approval")

    # 사용자 결정 분기
    graph.add_conditional_edges(
        "wait_approval",
        lambda s: "proceed" if s["user_decision"] in ("APPROVE", "MODIFY") else "end",
        {
            "proceed": "process_decision",
            "end": END,
        },
    )

    graph.add_edge("process_decision", "risk_recheck")

    # 리스크 재검증 분기
    graph.add_conditional_edges(
        "risk_recheck",
        lambda s: "execute" if s["risk_recheck_passed"] else "end",
        {
            "execute": "execute_sell",
            "end": END,
        },
    )

    graph.add_edge("execute_sell", "record_ledger")
    graph.add_edge("record_ledger", END)

    checkpointer = SqliteSaver.from_conn_string("data/langgraph_checkpoints.db")
    return graph.compile(checkpointer=checkpointer)
```

### 사용 흐름

```python
sell_graph = build_sell_approval_graph()

# 1. 매도 제안 생성 시 — 그래프 시작 (interrupt에서 멈춤)
thread_id = f"sell-{recommendation_id}"
result = sell_graph.invoke(
    {
        "recommendation_id": recommendation_id,
        "symbol": "005930",
        "market": "KR",
        "action": "SELL",
        "target_quantity": 50,
        "reason": "TRAILING_STOP_HIT",
        "score": -0.72,
        "confidence": 0.85,
        "created_at": datetime.utcnow().isoformat(),
        "errors": [],
    },
    config={"configurable": {"thread_id": thread_id}},
)
# → interrupt 상태로 대기 (체크포인트 저장됨)


# 2. 사용자 Telegram에서 /approve 시 — resume
from langgraph.types import Command

sell_graph.invoke(
    Command(resume={
        "decision": "APPROVE",
        "approved_at": datetime.utcnow().isoformat(),
    }),
    config={"configurable": {"thread_id": thread_id}},
)
# → risk_recheck → execute_sell → record_ledger → END


# 3. 수량 변경 시
sell_graph.invoke(
    Command(resume={
        "decision": "MODIFY",
        "modified_quantity": 30,
        "approved_at": datetime.utcnow().isoformat(),
    }),
    config={"configurable": {"thread_id": thread_id}},
)
```

### 타임아웃 만료 처리

```python
# Cloud Scheduler로 매시간 만료 체크 배치 실행
def expire_stale_recommendations():
    """승인 대기 N시간 초과 제안을 자동 만료"""
    max_hours = config.sell_recommendation.approval_timeout_hours  # 기본 48시간
    pending = get_pending_sell_workflows()

    for workflow in pending:
        if hours_since(workflow["created_at"]) > max_hours:
            sell_graph.invoke(
                Command(resume={
                    "decision": "TIMEOUT",
                    "approved_at": datetime.utcnow().isoformat(),
                }),
                config={"configurable": {"thread_id": workflow["thread_id"]}},
            )
            # → wait_approval에서 "end"로 분기 → 만료 기록
```