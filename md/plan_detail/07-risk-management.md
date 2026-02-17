# 07. 리스크 관리

> Phase 3 - Track A | 의존: Phase 2 Track A (신호 엔진) | 소요: Week 9~12

## 3계층 리스크 구조

```
신호 엔진 (BUY/SELL)
    │
    ▼
┌─────────────────────────────────┐
│  Level 1: 하드 리밋 (절대 한도)    │ ← 무조건 차단, 예외 없음
│  "이 한도를 넘으면 거래 불가"       │
└──────────────┬──────────────────┘
               │ 통과
               ▼
┌─────────────────────────────────┐
│  Level 2: 동적 리스크              │ ← 시장 상황에 따라 조정
│  "지금 상황에서 안전한가?"          │
└──────────────┬──────────────────┘
               │ 통과
               ▼
┌─────────────────────────────────┐
│  Level 3: AI 검증 (Phase 2+)     │ ← 환각/오류 방어
│  "AI 판단이 합리적인가?"           │
└──────────────┬──────────────────┘
               │ 통과
               ▼
           주문 실행
```

## Level 1: 하드 리밋

`config/settings.yaml`의 `risk.hard_limits` 섹션으로 관리.

```python
class HardLimitChecker:
    def check(self, order, portfolio) -> tuple[bool, str]:
        checks = [
            self._check_order_size(order),
            self._check_daily_orders(portfolio),
            self._check_daily_loss(portfolio),
            self._check_weekly_loss(portfolio),
            self._check_drawdown(portfolio),
            self._check_position_concentration(order, portfolio),
            self._check_sector_concentration(order, portfolio),
            self._check_total_positions(portfolio),
            self._check_cash_reserve(order, portfolio),
        ]
        for passed, reason in checks:
            if not passed:
                return False, reason  # 첫 번째 위반에서 즉시 차단
        return True, "ALL_PASSED"
```

| 규칙 | 설정 키 | 기본값 | 위반 시 |
|------|---------|--------|--------|
| 단일 주문 한도 (KR) | `max_single_order_krw` | 500만원 | 차단 |
| 단일 주문 한도 (US) | `max_single_order_usd` | $3,000 | 차단 |
| 일일 주문 횟수 | `max_orders_per_day` | 50 | 차단 |
| 일일 손실 | `max_daily_loss_pct` | -3% | 차단 + Kill Switch |
| 주간 손실 | `max_weekly_loss_pct` | -5% | 차단 |
| MDD | `max_drawdown_pct` | -15% | Kill Switch |
| 종목 비중 | `max_single_stock_pct` | 10% | 차단 |
| 섹터 비중 | `max_sector_pct` | 30% | 차단 |
| 총 포지션 수 | `max_total_positions` | 20 | 차단 |
| 최소 현금 | `min_cash_reserve_pct` | 20% | 차단 |

## Level 2: 동적 리스크

```python
class DynamicRiskChecker:
    def check(self, order, market_state) -> tuple[bool, str]:
        checks = [
            self._check_volatility(market_state),
            self._check_consecutive_loss(market_state),
            self._check_post_event_blackout(order),
            self._check_spread(order),
            self._check_circuit_breaker(market_state),
        ]
        # ...
```

| 조건 | 대응 | 설정 키 |
|------|------|---------|
| 변동성 과열 (상위 20%) | 포지션 크기 50% 축소 | `volatility_reduce_threshold` |
| 3연속 손실 | 1시간 매수 쿨다운 | `consecutive_loss_*` |
| 이벤트 직후 30초 | 주문 금지 | `post_event_blackout_seconds` |
| 스프레드 > 0.5% | 진입 금지 | `max_spread_pct` |
| 서킷브레이커 발동 | 전면 중지 | 자동 |

## Kill Switch

```python
class KillSwitch:
    AUTO_TRIGGERS = [
        "daily_loss_exceeded",        # 일일 손실 한도 초과
        "mdd_exceeded",               # MDD 한도 초과
        "api_consecutive_failures",   # API 연속 실패 5회
        "data_gap_minutes",           # 데이터 공백 30분
    ]

    def activate(self, reason: str):
        # 1. 신규 주문 전면 차단
        redis.set("kill_switch:active", "true")
        redis.set("kill_switch:reason", reason)

        # 2. 미체결 주문 전량 취소
        cancel_all_pending_orders()

        # 3. 즉시 알림
        send_telegram_alert(f"KILL SWITCH 발동: {reason}")

        # 4. 감사 로그 기록
        log_to_bigquery("kill_switch", reason)

    def is_active(self) -> bool:
        return redis.get("kill_switch:active") == "true"

    def deactivate(self):
        """수동으로만 해제 가능"""
        # 자동 해제 없음 — 반드시 사용자가 상황을 확인하고 수동 해제
```

## 손절 전략

```python
def check_stop_loss(position) -> str | None:
    current = get_current_price(position.symbol)
    entry = position.avg_cost
    peak = position.peak_price  # 보유 중 최고가

    # 고정 손절: 매수가 대비 -5%
    if (current - entry) / entry < config.risk.stop_loss.fixed_pct:
        return "FIXED_STOP"

    # 트레일링 손절: 고점 대비 -3%
    if (current - peak) / peak < config.risk.stop_loss.trailing_pct:
        return "TRAILING_STOP"

    # 시간 손절: 5일 보유 + -2% 미만
    days_held = (now() - position.opened_at).days
    pnl_pct = (current - entry) / entry
    if days_held >= config.risk.stop_loss.time_days:
        if pnl_pct < config.risk.stop_loss.time_loss_pct:
            return "TIME_STOP"

    return None
```

## 감사 로그

모든 리스크 판정은 BigQuery `decision_logs`에 기록:

```json
{
    "decision_id": "uuid",
    "ts_utc": "2026-02-16T09:05:00Z",
    "symbol": "005930",
    "decision": "BUY",
    "risk_check": {
        "passed": false,
        "level": 2,
        "blocker": "CONSECUTIVE_LOSS_COOLDOWN",
        "checks": [
            {"level": 1, "rule": "position_limit", "result": "OK"},
            {"level": 1, "rule": "daily_loss", "result": "OK"},
            {"level": 2, "rule": "consecutive_loss", "result": "BLOCKED"}
        ]
    },
    "final_action": "HOLD",
    "reason_codes": ["RISK_BLOCKED", "CONSECUTIVE_LOSS_COOLDOWN"]
}
```

## 완료 기준

- [ ] Level 1 하드 리밋: 한도 초과 시 100% 차단 확인
- [ ] Level 2 동적 리스크: 연속 손실 쿨다운 정상 동작
- [ ] Kill Switch: 발동 → 미체결 취소 → 알림 → 로그 기록
- [ ] Kill Switch 해제: 수동으로만 가능 확인
- [ ] 손절 3종: 고정/트레일링/시간 정상 동작
- [ ] 감사 로그: 모든 판정 BigQuery 기록 100%

---

## Hybrid Update (2026-02-16)

### Agent 결과 리스크 반영 규칙
- Agent의 자신감(confidence)이 임계값 미만이면 Numeric 결과만 사용한다.
- Agent가 강한 매도 신호를 내도 Hard Limit/시장상태 제약을 우회할 수 없다.
- 수동입력 포지션이 최신이 아니면(`stale`) 신규 매도 실행을 차단하고 경고만 발송한다.

### 신규 점검 항목
- `MANUAL_POSITION_STALE`
- `AGENT_TIMEOUT_FALLBACK_NUMERIC`
- `SELL_RECOMMENDATION_REQUIRES_CONFIRMATION`