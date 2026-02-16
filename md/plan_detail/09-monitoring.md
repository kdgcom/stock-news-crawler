# 09. 모니터링 & 알림

> Phase 3 - Track B | 병렬 진행 가능 | 소요: Week 9~12

## 알림 채널: Telegram

### Google Chat을 사용하지 않는 이유

Google Chat의 Incoming Webhook은 **Google Workspace (유료)** 계정에서만 사용 가능하다.
개인 Gmail 계정으로는 봇 메시지를 보낼 수 없으므로 Telegram을 선택한다.

### Telegram 선정 사유

| 기준 | Telegram | Discord | Slack | Google Chat |
|------|----------|---------|-------|-------------|
| 무료 | O | O | 제한적 | X (Workspace 필요) |
| Bot API | 간편 | Webhook만 | 복잡 | 불가 (개인) |
| 모바일 푸시 | 즉시 | 즉시 | 즉시 | — |
| Rate Limit | 30msg/sec | 50msg/min | 1msg/sec | — |
| 트레이딩 봇 생태계 | 풍부 | 보통 | 보통 | 없음 |

### Telegram 봇 설정

```python
import httpx

class TelegramNotifier:
    def __init__(self, config):
        self.token = config.notification.telegram.bot_token
        self.chat_id = config.notification.telegram.chat_id
        self.base_url = f"https://api.telegram.org/bot{self.token}"

    def send(self, message: str, parse_mode: str = "HTML"):
        # 무음 시간 확인
        if self._is_quiet_hours():
            return

        httpx.post(f"{self.base_url}/sendMessage", json={
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": parse_mode,
        })
```

## 알림 종류 및 시점

| 알림 | 시점 | 중요도 | 설정 키 |
|------|------|--------|---------|
| **KR Morning Briefing** | 08:30 KST | 정보 | `send_daily_briefing` |
| **US Evening Briefing** | 23:00 KST | 정보 | `send_daily_briefing` |
| **매매 신호** | 신호 생성 시 | 보통 | `send_trade_signals` |
| **리스크 경고** | 한도 80% 도달 | 높음 | `send_risk_alerts` |
| **Kill Switch 발동** | 즉시 | 긴급 | `send_kill_switch` |
| **주간 리포트** | 토요일 10:00 | 정보 | `send_weekly_report` |
| **시스템 장애** | 즉시 | 긴급 | 항상 발송 |
| **비용 경고** | LLM $7/일 초과 | 높음 | 항상 발송 |

### 알림 포맷 예시

```
# 매매 신호
🟢 BUY 005930 삼성전자
Score: 0.72 | Confidence: 0.85
Sentiment: +0.82 | Technical: +0.55
Size: ₩3,500,000 (7%)

# 리스크 경고
⚠️ 일일 손실 -2.1% (한도 -3.0%)
잔여 여력: 0.9%
현재 포지션: 8종목

# Kill Switch
🚨 KILL SWITCH 발동
사유: 일일 손실 한도 초과 (-3.2%)
조치: 미체결 3건 취소 완료
상태: 신규 매매 전면 차단
해제: 수동 확인 필요
```

## Prometheus 메트릭

### 수집 메트릭

```python
from prometheus_client import Counter, Histogram, Gauge

# 데이터 수집
news_collected = Counter("news_collected_total", "수집된 뉴스 수", ["market", "source"])
price_collected = Counter("price_collected_total", "수집된 시세 수", ["market"])
collection_latency = Histogram("collection_latency_seconds", "수집 지연", ["market", "type"])
collection_errors = Counter("collection_errors_total", "수집 오류", ["market", "source"])

# 트레이딩
signals_generated = Counter("signals_total", "신호 생성", ["market", "decision"])
orders_executed = Counter("orders_total", "주문 체결", ["market", "side"])
risk_blocks = Counter("risk_blocks_total", "리스크 차단", ["level", "reason"])
daily_pnl = Gauge("daily_pnl_pct", "일일 손익률")
total_positions = Gauge("total_positions", "보유 종목 수")

# 시스템
bigquery_load_latency = Histogram("bq_load_seconds", "BQ 배치 로드 시간")
redis_memory_used = Gauge("redis_memory_bytes", "Redis 메모리 사용량")
llm_daily_cost = Gauge("llm_daily_cost_usd", "LLM 일일 비용")
```

### 경보 규칙

| 카테고리 | 조건 | 경보 |
|---------|------|------|
| 데이터 | 수집 공백 > 15분 | Telegram 경고 |
| 데이터 | 수집 오류 연속 5회 | Telegram 경고 |
| 트레이딩 | 일일 손실 > -2% | Telegram 경고 |
| 트레이딩 | 일일 손실 > -3% | Kill Switch + 긴급 알림 |
| 시스템 | Redis 메모리 > 200MB | Telegram 경고 |
| 비용 | LLM 일일 > $7 | 모델 전환 + 경고 |

## Grafana 대시보드

Grafana Cloud 무료 티어 (10K metrics, 50GB logs) 활용.

### 대시보드 구성

```
┌─────────────────────────────────────────────────┐
│  Stock Trading Dashboard                        │
├───────────────┬─────────────────────────────────┤
│ Portfolio     │  Daily P&L Chart                │
│ ₩50,000,000  │  [====━━━━━━━━━━━━━━━]           │
│ +1.2% today  │                                  │
├───────────────┼─────────────────────────────────┤
│ Positions: 8  │  Signal Distribution             │
│ Cash: 62%    │  BUY: 12 | SELL: 3 | HOLD: 63   │
├───────────────┼─────────────────────────────────┤
│ Risk Status  │  Collection Health               │
│ Daily: -0.8% │  KR News: ✓ | KR Price: ✓       │
│ Weekly: -1.2% │  US News: ✓ | US Price: ✓       │
│ MDD: -2.3%   │  Last: 2min ago                  │
└───────────────┴─────────────────────────────────┘
```

## 일일 리포트 (장 마감 후)

```
📈 KR Daily Report (2026-02-16)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

■ 오늘의 성과
  일일 수익률: +1.2%
  실현 손익: +₩120,000
  미실현 손익: +₩350,000

■ 매매 내역
  BUY  005930 삼성전자 100주 @ ₩58,200
  SELL 035720 카카오뱅크 200주 @ ₩25,300 (+3.2%)

■ 신호 통계
  생성: 78건 | BUY: 5 | SELL: 2 | HOLD: 71
  리스크 차단: 1건 (스프레드 초과)

■ 포트폴리오 현황
  총 자산: ₩50,600,000 (+1.2%)
  보유: 8종목 | 현금: 60%
  MDD: -2.3% (한도 -15%)

■ 내일 주목
  - 삼성전자 실적발표 (D-2)
  - FOMC 의사록 공개 결과 반영
```

## 완료 기준

- [ ] Telegram 봇 메시지 발송 정상
- [ ] Morning/Evening Briefing 자동 발송
- [ ] Kill Switch 알림 즉시 발송 (< 5초)
- [ ] Prometheus 메트릭 수집 정상
- [ ] Grafana 대시보드 구성 완료
- [ ] 일일 리포트 자동 생성/발송
- [ ] 무음 시간(00:00~06:00) 적용 확인

---

## Hybrid Update (2026-02-16)

### 신규 모니터링 지표
- `hybrid_agent_trigger_total` : Agent 호출 횟수
- `hybrid_fallback_numeric_total` : Agent 실패 후 Numeric 폴백 횟수
- `manual_portfolio_freshness_hours` : 마지막 수동입력 이후 경과시간
- `sell_recommendation_generated_total` : 매도 제안 생성 수
- `sell_recommendation_approved_total` : 사용자 승인 수

### 신규 알림 규칙
- 수동입력 24시간 미갱신 시 경고
- Agent 타임아웃 비율 임계값 초과 시 경고
- 고신뢰 매도 제안 누적(예: 3회 이상) 미확인 시 리마인드
## Trade Ledger Update (2026-02-16)
- `trade_ledger_buy_total`, `trade_ledger_sell_total`
- `sell_block_no_open_position_total`
- `holding_recalc_latency_ms`