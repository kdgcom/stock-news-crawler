# 01. 설정 파일 가이드

## 설정 파일 위치

```
config/
├── settings.yaml              ← 템플릿 (Git 커밋, 비밀값 없음)
├── settings.local.yaml        ← 실제 운영 설정 (.gitignore)
└── gcp-service-account.json   ← GCP 서비스 계정 키 (.gitignore)
```

## 초기 설정 순서

### 1단계: 설정 파일 복사

```bash
cp config/settings.yaml config/settings.local.yaml
```

### 2단계: GCP 계정 설정

```yaml
gcp:
  account_email: "your-email@gmail.com"
  project_id: "stock-trading-xxxxx"
  region: "us-central1"               # 변경 금지 (무료 티어 대상)
```

> **주의**: `region`은 `us-central1`을 유지해야 e2-micro VM, Cloud Storage 등이 무료 대상이 된다.

### 3단계: BigQuery 데이터셋

```yaml
gcp:
  bigquery:
    dataset: "stock_trading"           # 원하는 데이터셋명
    location: "US"                     # 무료 티어 대상
```

### 4단계: MongoDB Atlas 연결

```yaml
mongodb:
  atlas_uri: "mongodb+srv://user:password@cluster.xxxxx.mongodb.net"
  database: "stock_news"
```

### 5단계: Telegram 봇 설정

```yaml
notification:
  provider: "telegram"
  telegram:
    bot_token: "123456:ABC-xxxxx"      # @BotFather에서 생성
    chat_id: "987654321"               # 봇과 대화 후 chat_id 확인
```

Telegram 봇 생성 절차:
1. Telegram에서 @BotFather 검색 → `/newbot` 명령
2. 봇 이름 설정 → `bot_token` 수령
3. 생성된 봇에게 아무 메시지 전송
4. `https://api.telegram.org/bot{TOKEN}/getUpdates` 에서 `chat_id` 확인

### 6단계: 브로커 API (Phase 3에서 설정)

```yaml
broker:
  kr:
    provider: "kis"
    app_key: ""                        # 한국투자증권 API 키
    app_secret: ""
    account_no: ""
    is_paper: true                     # 반드시 true로 시작
```

## 주요 설정값 설명

### 수집 주기

| 설정 | 기본값 | 설명 |
|------|--------|------|
| `collection.price.interval_minutes` | 5 | 시세 수집 주기 |
| `collection.news.interval_minutes` | 5 | 뉴스 수집 주기 |
| `collection.news.pre_market_lookback_hours` | 12 | 장전 스캔 시 과거 탐색 범위 |

### 저장 보존 기간

| 설정 | 기본값 | 설명 |
|------|--------|------|
| `storage.retention.price_5m_bars_months` | 12 | 5분봉 보존 (월) |
| `storage.retention.daily_bars` | permanent | 일봉 영구 보존 |
| `storage.retention.news_raw_mongodb_days` | 90 | MongoDB raw 보존 (일) |
| `storage.retention.news_enriched` | permanent | enriched 영구 보존 |

### 리스크 설정

| 설정 | 기본값 | 설명 |
|------|--------|------|
| `risk.hard_limits.max_daily_loss_pct` | -0.03 | 일일 최대 손실 -3% |
| `risk.hard_limits.max_drawdown_pct` | -0.15 | MDD -15% → Kill Switch |
| `risk.hard_limits.max_total_positions` | 20 | 최대 보유 종목 수 |
| `risk.hard_limits.max_single_stock_pct` | 0.10 | 종목당 최대 비중 10% |

### 분석 엔진

| 설정 | 기본값 | 설명 |
|------|--------|------|
| `analysis.signal.buy_threshold` | 0.6 | 매수 신호 임계값 |
| `analysis.signal.sell_threshold` | -0.6 | 매도 신호 임계값 |
| `analysis.sentiment.phase` | 1 | 감성 분석 단계 (1=키워드, 2=LLM) |

## 환경별 설정 오버라이드

```python
# 설정 로드 우선순위
# 1. config/settings.yaml (기본값)
# 2. config/settings.local.yaml (로컬 오버라이드)
# 3. 환경 변수 (STOCK_GCP_PROJECT_ID 등)

import yaml
from pathlib import Path

def load_config():
    base = yaml.safe_load(Path("config/settings.yaml").read_text())
    local_path = Path("config/settings.local.yaml")
    if local_path.exists():
        local = yaml.safe_load(local_path.read_text())
        deep_merge(base, local)
    return base
```

## .gitignore 추가 항목

```gitignore
# 비밀 설정
config/settings.local.yaml
config/gcp-service-account.json
.env
```

---

## Hybrid Update (2026-02-16)

### 신규 설정: Hybrid 알고리즘
```yaml
analysis:
  mode: hybrid                # numeric | agent | hybrid
  hybrid:
    alpha_default: 0.7
    alpha_volatile: 0.5
    alpha_news_spike: 0.4
    agent_trigger:
      near_threshold_margin: 0.12
      conflict_required: true
      high_impact_event_types: ["earnings", "m_and_a", "regulation", "lawsuit"]
    fail_safe:
      on_agent_timeout: "numeric_only"
      timeout_ms: 2500
      max_agent_calls_per_day: 5000
```

### 신규 설정: 보유종목 수동입력/매도제안
```yaml
portfolio_input:
  provider: cloud_functions
  enabled: true
  auth_mode: "google_oauth"
  refresh_required_hours: 24

sell_recommendation:
  enabled: true
  min_confidence: 0.6
  recommendation_actions: ["SELL", "REDUCE", "HOLD"]
  require_user_confirmation: true
```
## Trade Ledger Update (2026-02-16)
```yaml
trade_ledger:
  enabled: true
  record_buy: true
  record_sell: true
  source_priority: ["broker_fill", "manual_input"]
  holding_calculation: "fifo"

sell_recommendation:
  holdings_only: true
  min_holding_quantity: 1
  block_if_no_open_position: true
```