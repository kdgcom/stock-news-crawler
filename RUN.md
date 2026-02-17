# 실행 가이드

## claude

### 사전 요구사항

- Python 3.11+
- pip

### 설치

```bash
pip install -r requirements.txt
```

### 설정

1. 설정 파일 복사:

```bash
cp config/settings.yaml config/settings.local.yaml
```

2. `config/settings.local.yaml`을 열어 아래 항목을 실제 값으로 수정:

| 항목 | 설명 |
|------|------|
| `gcp.project_id` | GCP 프로젝트 ID |
| `gcp.credentials_path` | GCP 서비스 계정 키 JSON 경로 |
| `mongodb.atlas_uri` | MongoDB Atlas 연결 URI |
| `redis.host` / `redis.password` | Redis 접속 정보 (로컬 또는 Upstash) |
| `notification.telegram.bot_token` | Telegram 봇 토큰 |
| `notification.telegram.chat_id` | Telegram 채팅 ID |
| `universe.tier1.kr.symbols` | KR Tier 1 감시 종목 목록 |
| `universe.tier1.us.symbols` | US Tier 1 감시 종목 목록 |

3. (선택) 환경 변수로 오버라이드 가능:

```bash
export STOCK_GCP_PROJECT_ID="my-project"
export STOCK_MONGODB_URI="mongodb+srv://..."
export STOCK_TELEGRAM_BOT_TOKEN="123456:ABC..."
export STOCK_TELEGRAM_CHAT_ID="987654321"
```

### 실행

#### 단일 분석 사이클 (기본)

```bash
python main.py --mode claude
```

#### 연속 서버 모드

```bash
python main.py --mode claude --run-mode server
```

#### 옵션

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `--run-mode once` | `once` | 단일 사이클 실행 후 종료 |
| `--run-mode server` | - | 연속 실행 (설정된 interval마다 반복) |
| `--log-level DEBUG` | `INFO` | 로그 수준 (DEBUG/INFO/WARNING/ERROR) |
| `--config <path>` | `config/settings.yaml` | 기본 설정 파일 경로 지정 |

### 동작 흐름

1. `config/settings.yaml` + `config/settings.local.yaml` 로드
2. 인프라 클라이언트 초기화 (BigQuery, MongoDB, Redis, GCS, Telegram)
3. 분석 엔진 초기화 (8종 알고리즘 + Ensemble)
4. Tier 1 종목 순회 분석:
   - AlgorithmContext 구성
   - AlgorithmRouter → Signal 생성
   - RiskGate 3계층 검증
   - PaperExecutor 가상 체결
5. 결과 로깅 및 Telegram 알림

### 프로젝트 구조 (claude_impl)

```
src/claude_impl/
├── app.py                 # 진입점
├── config/loader.py       # YAML 설정 로더
├── models/                # 데이터 모델 (News, Price, Signal, Position, Trade)
├── infrastructure/        # 클라이언트 (BigQuery, MongoDB, Redis, GCS, Telegram)
├── collection/            # 데이터 수집기 (KR/US 뉴스, 시세)
├── storage/               # 데이터 저장 (news_writer, price_writer, cache, archiver)
├── premarket/             # 장전 루틴 + LangGraph BriefingGraph
├── analysis/              # 분석 엔진 (8 알고리즘 + Ensemble + Hybrid + LangGraph)
├── risk/                  # 리스크 관리 (3계층 + Kill Switch)
├── execution/             # 매매 실행 (Paper + Ledger + LangGraph SellApproval)
├── monitoring/            # 모니터링 (Prometheus + Telegram 알림)
└── universe/              # 종목 유니버스 (3-Tier 관리)
```
