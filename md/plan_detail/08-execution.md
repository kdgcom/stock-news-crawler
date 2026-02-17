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