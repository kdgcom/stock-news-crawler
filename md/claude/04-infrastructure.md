# 인프라 및 배포

## 1. 인프라 구성 개요

자동 트레이딩 시스템은 **24시간 안정 운영**이 핵심이다. 국내 장(09:00~15:30 KST)과 미국 장(23:30~06:00 KST)을 모두 커버해야 하므로 사실상 하루의 대부분을 운영해야 한다.

---

## 2. 배포 환경 선택지

### 2.1 옵션 비교

| 옵션 | 장점 | 단점 | 월 비용 (추정) |
|------|------|------|---------------|
| **로컬 서버 (Docker)** | 지연 최소, 비용 낮음, 완전 제어 | 장애 시 수동 대응, 전원/네트워크 의존 | 전기세만 |
| **클라우드 VPS** | 안정성 높음, 원격 관리 | 네트워크 지연, 월 비용 | $20~$80 |
| **클라우드 (AWS/GCP)** | 확장성, 관리형 서비스 | 비용 높음, 복잡도 | $50~$200+ |

### 2.2 권장: 하이브리드 (로컬 + 클라우드 백업)

```
┌─ 로컬 서버 (메인) ─────────────────────────┐
│  Docker Compose                             │
│  ├── MongoDB (기존)                          │
│  ├── TimescaleDB                             │
│  ├── Redis                                   │
│  ├── news-crawler                            │
│  ├── price-feeder                            │
│  ├── ai-agent                                │
│  ├── executor                                │
│  └── dashboard (FastAPI + Grafana)           │
└─────────────────────────────────────────────┘
                    │
                    │ 장애 감지 시 자동 전환
                    ▼
┌─ 클라우드 VPS (백업) ──────────────────────┐
│  최소 구성 (크롤러 + 에이전트 + 실행기)       │
│  ※ 평소에는 데이터 동기화만 수행              │
└─────────────────────────────────────────────┘
```

---

## 3. Docker Compose 구성

### 3.1 docker-compose.yml 설계

```yaml
version: "3.9"

services:
  # ─── 데이터베이스 ───
  mongodb:
    image: mongodb/mongodb-community-server:latest
    container_name: stock-mongodb
    environment:
      MONGODB_INITDB_ROOT_USERNAME: ${MONGO_USER}
      MONGODB_INITDB_ROOT_PASSWORD: ${MONGO_PASS}
    ports:
      - "27017:27017"
    volumes:
      - mongodb_data:/data/db
    restart: always

  timescaledb:
    image: timescale/timescaledb:latest-pg16
    container_name: stock-timescaledb
    environment:
      POSTGRES_USER: ${TSDB_USER}
      POSTGRES_PASSWORD: ${TSDB_PASS}
      POSTGRES_DB: stock_prices
    ports:
      - "5432:5432"
    volumes:
      - timescaledb_data:/var/lib/postgresql/data
    restart: always

  redis:
    image: redis:7-alpine
    container_name: stock-redis
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    restart: always

  # ─── 애플리케이션 ───
  news-crawler:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: stock-news-crawler
    command: python -m src.collectors.run_crawlers
    env_file: .env
    depends_on:
      - mongodb
      - redis
    restart: always
    volumes:
      - ./logs:/app/logs

  price-feeder:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: stock-price-feeder
    command: python -m src.collectors.run_price_feed
    env_file: .env
    depends_on:
      - timescaledb
      - redis
    restart: always
    volumes:
      - ./logs:/app/logs

  ai-agent:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: stock-ai-agent
    command: python -m src.agents.run_agent
    env_file: .env
    depends_on:
      - mongodb
      - timescaledb
      - redis
    restart: always
    volumes:
      - ./logs:/app/logs

  executor:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: stock-executor
    command: python -m src.brokers.run_executor
    env_file: .env
    depends_on:
      - ai-agent
    restart: always
    volumes:
      - ./logs:/app/logs

  # ─── 모니터링 ───
  dashboard:
    build:
      context: ./dashboard
      dockerfile: Dockerfile
    container_name: stock-dashboard
    ports:
      - "8000:8000"
    env_file: .env
    depends_on:
      - mongodb
      - timescaledb
    restart: always

  grafana:
    image: grafana/grafana:latest
    container_name: stock-grafana
    ports:
      - "3000:3000"
    volumes:
      - grafana_data:/var/lib/grafana
      - ./monitoring/grafana/dashboards:/etc/grafana/provisioning/dashboards
    restart: always

  prometheus:
    image: prom/prometheus:latest
    container_name: stock-prometheus
    ports:
      - "9090:9090"
    volumes:
      - ./monitoring/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus_data:/prometheus
    restart: always

volumes:
  mongodb_data:
  timescaledb_data:
  redis_data:
  grafana_data:
  prometheus_data:
```

### 3.2 Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 타임존 설정 (한국 시간)
ENV TZ=Asia/Seoul
RUN ln -sf /usr/share/zoneinfo/$TZ /etc/localtime

CMD ["python", "main.py"]
```

---

## 4. 환경 변수 관리

### 4.1 .env 파일 확장

```bash
# ─── 데이터베이스 ───
MONGO_USER=wicean
MONGO_PASS=secure_password_here
MONGODB_URI=mongodb://${MONGO_USER}:${MONGO_PASS}@mongodb:27017

TSDB_USER=stock_user
TSDB_PASS=secure_password_here
TSDB_URI=postgresql://${TSDB_USER}:${TSDB_PASS}@timescaledb:5432/stock_prices

REDIS_URL=redis://redis:6379

# ─── 증권사 API ───
KIS_APP_KEY=your_kis_app_key
KIS_APP_SECRET=your_kis_app_secret
KIS_ACCOUNT_NO=your_account_number
KIS_MOCK=true                          # true: 모의투자, false: 실전

ALPACA_API_KEY=your_alpaca_key
ALPACA_SECRET_KEY=your_alpaca_secret
ALPACA_BASE_URL=https://paper-api.alpaca.markets  # paper: 모의, api: 실전

# ─── AI/LLM ───
ANTHROPIC_API_KEY=your_claude_api_key
OPENAI_API_KEY=your_openai_api_key     # 대체 또는 보조

# ─── 뉴스 API ───
DART_API_KEY=your_dart_api_key
MARKETAUX_API_KEY=your_marketaux_key

# ─── 알림 ───
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/xxx
TELEGRAM_BOT_TOKEN=your_telegram_token
TELEGRAM_CHAT_ID=your_chat_id

# ─── 운영 ───
LOG_LEVEL=INFO
ENVIRONMENT=development                 # development | staging | production
```

---

## 5. 모니터링 시스템

### 5.1 모니터링 대상

```
┌─────────────────────────────────────────────────────────┐
│                    Grafana Dashboard                     │
│                                                         │
│  ┌─────────────────┐  ┌──────────────────────────────┐  │
│  │ 시스템 메트릭     │  │ 트레이딩 메트릭               │  │
│  │ - CPU / 메모리   │  │ - 일일 수익률                 │  │
│  │ - 디스크 사용량   │  │ - 누적 수익률                 │  │
│  │ - 네트워크 상태   │  │ - 포트폴리오 가치              │  │
│  │ - 컨테이너 상태   │  │ - MDD (최대 낙폭)            │  │
│  └─────────────────┘  │ - 승률 / 손익비               │  │
│                        └──────────────────────────────┘  │
│  ┌─────────────────┐  ┌──────────────────────────────┐  │
│  │ 데이터 파이프라인 │  │ AI 에이전트 상태               │  │
│  │ - 크롤링 건수/분  │  │ - 분석 처리 건수               │  │
│  │ - 수집 지연      │  │ - LLM API 호출 횟수/비용      │  │
│  │ - 에러 발생률    │  │ - 시그널 발생 현황              │  │
│  │ - DB 적재 현황   │  │ - 최근 매매 기록               │  │
│  └─────────────────┘  └──────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### 5.2 핵심 메트릭 수집 (Prometheus)

```python
from prometheus_client import Counter, Gauge, Histogram, start_http_server

# 크롤링 메트릭
news_crawled_total = Counter(
    'news_crawled_total', 'Total news articles crawled',
    ['source', 'market']
)
crawl_latency = Histogram(
    'crawl_latency_seconds', 'Time to crawl a news source',
    ['source']
)

# 트레이딩 메트릭
portfolio_value = Gauge(
    'portfolio_value_krw', 'Current portfolio value in KRW'
)
daily_pnl = Gauge(
    'daily_pnl_pct', 'Daily P&L percentage'
)
trade_executed = Counter(
    'trade_executed_total', 'Total trades executed',
    ['action', 'market', 'status']
)

# AI 메트릭
llm_api_calls = Counter(
    'llm_api_calls_total', 'Total LLM API calls',
    ['model', 'purpose']
)
llm_api_cost = Counter(
    'llm_api_cost_usd', 'Cumulative LLM API cost in USD',
    ['model']
)
sentiment_score = Gauge(
    'sentiment_score', 'Latest sentiment score per ticker',
    ['ticker']
)
```

### 5.3 알림 규칙

```python
ALERT_RULES = {
    # 시스템 장애
    "crawler_down": {
        "condition": "크롤링 0건/5분 이상",
        "severity": "critical",
        "action": "Slack + Telegram 즉시 알림"
    },
    "websocket_disconnect": {
        "condition": "WebSocket 연결 끊김 30초 이상",
        "severity": "critical",
        "action": "자동 재연결 시도 + 알림"
    },
    "db_connection_lost": {
        "condition": "DB 연결 실패",
        "severity": "critical",
        "action": "모든 거래 중단 + 알림"
    },

    # 트레이딩 알림
    "trade_executed": {
        "condition": "매수 또는 매도 체결",
        "severity": "info",
        "action": "Telegram 알림 (종목, 수량, 가격)"
    },
    "daily_loss_limit": {
        "condition": "일일 손실 > -3%",
        "severity": "warning",
        "action": "금일 신규 매수 중단 + 알림"
    },
    "max_drawdown_breach": {
        "condition": "MDD > -15%",
        "severity": "critical",
        "action": "모든 거래 중단 + 전체 포지션 정리 검토 알림"
    },

    # 비용 관리
    "llm_daily_cost": {
        "condition": "일일 LLM 비용 > $10",
        "severity": "warning",
        "action": "Haiku 모델로 전환 알림"
    }
}
```

---

## 6. 로깅 체계

### 6.1 로그 구조

```python
import logging
import json
from datetime import datetime

class StructuredLogger:
    """JSON 구조화 로깅"""

    def __init__(self, name: str, log_dir: str = "./logs"):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.INFO)

        # 파일 핸들러 (일별 로테이션)
        handler = logging.handlers.TimedRotatingFileHandler(
            f"{log_dir}/{name}.log",
            when="midnight",
            backupCount=30
        )
        handler.setFormatter(logging.Formatter('%(message)s'))
        self.logger.addHandler(handler)

    def log(self, level: str, event: str, **kwargs):
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": level,
            "event": event,
            **kwargs
        }
        getattr(self.logger, level)(json.dumps(entry, ensure_ascii=False))
```

### 6.2 로그 분류

```
logs/
├── crawler.log          # 크롤링 활동 로그
├── analyzer.log         # 분석 처리 로그
├── trading.log          # 매매 의사결정 로그 (가장 중요)
├── execution.log        # 주문 실행 로그
├── error.log            # 전체 에러 로그
└── audit.log            # 감사 추적 로그 (변경 불가)
```

**trading.log 예시:**
```json
{
    "timestamp": "2025-06-15T09:30:15.123Z",
    "level": "info",
    "event": "signal_generated",
    "ticker": "005930",
    "market": "KRX",
    "action": "BUY",
    "score": 0.67,
    "reasons": {
        "sentiment": {"score": 0.72, "source": "뉴스 5건 분석"},
        "technical": {"score": 0.55, "source": "RSI=32, MACD 골든크로스"},
        "fundamental": {"score": 0.68, "source": "PER 11.2 저평가"}
    },
    "risk_check": "passed",
    "order_quantity": 10,
    "order_price": 72500
}
```

---

## 7. 장애 대응 전략

### 7.1 장애 시나리오별 대응

| 장애 유형 | 감지 방법 | 자동 대응 | 수동 대응 |
|-----------|----------|-----------|-----------|
| **크롤러 중단** | 5분간 뉴스 0건 | 프로세스 재시작 | 원인 분석 |
| **WebSocket 끊김** | heartbeat 미수신 | 자동 재연결 (지수 백오프) | - |
| **DB 장애** | 연결 실패 3회 | 거래 중단, 메모리 버퍼 | DB 복구 |
| **LLM API 장애** | 타임아웃/에러 | 캐시 결과 사용, 기술적 분석만으로 판단 | - |
| **증권사 API 장애** | 주문 실패 | 재시도 3회 후 중단 | 수동 주문 |
| **서버 전원 차단** | UPS 신호 | 미체결 주문 취소, 안전 종료 | 서버 재가동 |

### 7.2 Health Check

```python
class HealthChecker:
    async def check_all(self) -> dict:
        return {
            "mongodb": await self.check_mongodb(),
            "timescaledb": await self.check_timescaledb(),
            "redis": await self.check_redis(),
            "kis_api": await self.check_kis_api(),
            "alpaca_api": await self.check_alpaca_api(),
            "llm_api": await self.check_llm_api(),
            "crawler": await self.check_crawler_running(),
            "overall": "healthy" if all_passed else "degraded"
        }
```

---

## 8. 데이터 백업

### 8.1 백업 정책

| 데이터 | 백업 주기 | 보관 기간 | 방법 |
|--------|----------|----------|------|
| **MongoDB (뉴스, 시그널)** | 매일 | 1년 | mongodump → 압축 → 외부 저장소 |
| **TimescaleDB (시세)** | 매주 | 영구 (시세 데이터) | pg_dump → 압축 |
| **거래 기록** | 실시간 | 영구 | MongoDB replica + 외부 백업 |
| **설정/코드** | 커밋마다 | 영구 | Git |
| **로그** | 매일 | 3개월 | 로테이션 + 압축 |
