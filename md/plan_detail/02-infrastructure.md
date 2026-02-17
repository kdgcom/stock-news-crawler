# 02. GCP 인프라 셋업

> Phase 1 - Track A | 담당: 인프라 | 소요: Week 1~3

## 전제 조건

- Google 계정 (Gmail)
- `config/settings.local.yaml`에 계정 정보 입력 완료

## 셋업 순서

### Step 1: GCP 프로젝트 생성 (Week 1)

```bash
# gcloud CLI 설치 후
gcloud auth login
gcloud projects create stock-trading-$(date +%s) --name="Stock Trading"
gcloud config set project [PROJECT_ID]

# 결제 계정 연결 (무료 티어 활성화 필수)
gcloud billing accounts list
gcloud billing projects link [PROJECT_ID] --billing-account=[ACCOUNT_ID]
```

필요 API 활성화:

```bash
gcloud services enable \
  bigquery.googleapis.com \
  run.googleapis.com \
  cloudscheduler.googleapis.com \
  storage.googleapis.com \
  compute.googleapis.com
```

### Step 2: BigQuery 데이터셋 (Week 1)

```bash
bq mk --location=US stock_trading
```

테이블 생성은 `04-data-storage.md` 참조.

### Step 3: Cloud Storage 버킷 (Week 1)

```bash
# 배치 로드 버퍼 + 뉴스 아카이브
gsutil mb -l us-central1 gs://[PROJECT_ID]-stock-data/
```

### Step 4: e2-micro VM (Week 1)

```bash
gcloud compute instances create stock-vm \
  --zone=us-central1-a \
  --machine-type=e2-micro \
  --image-family=ubuntu-2204-lts \
  --image-project=ubuntu-os-cloud \
  --boot-disk-size=30GB \
  --tags=stock-vm
```

VM 초기 설정:

```bash
# SSH 접속 후
sudo apt update && sudo apt install -y redis-server python3.11 python3.11-venv

# Redis 설정
sudo systemctl enable redis-server
sudo systemctl start redis-server

# Redis AOF 영속화 활성화
sudo sed -i 's/appendonly no/appendonly yes/' /etc/redis/redis.conf
sudo systemctl restart redis-server
```

### Step 5: Cloud Run 서비스 배포 (Week 2~3)

```bash
# Dockerfile 기반 배포
gcloud run deploy news-collector \
  --source . \
  --region us-central1 \
  --allow-unauthenticated=false \
  --service-account=[SA_EMAIL] \
  --max-instances=3 \
  --timeout=300

# 추가 서비스: price-collector, analyzer, risk-checker
```

### Step 6: Cloud Scheduler (Week 3)

```bash
# KR 장중 5분마다 (KST 09:00~15:30)
gcloud scheduler jobs create http kr-price-collect \
  --schedule="*/5 9-15 * * 1-5" \
  --time-zone="Asia/Seoul" \
  --uri="https://[CLOUD_RUN_URL]/collect/kr/price" \
  --http-method=POST

# KR 뉴스 5분마다
gcloud scheduler jobs create http kr-news-collect \
  --schedule="*/5 7-16 * * 1-5" \
  --time-zone="Asia/Seoul" \
  --uri="https://[CLOUD_RUN_URL]/collect/kr/news" \
  --http-method=POST

# KR 장전 브리핑 (07:30 KST)
gcloud scheduler jobs create http kr-morning-briefing \
  --schedule="30 7 * * 1-5" \
  --time-zone="Asia/Seoul" \
  --uri="https://[CLOUD_RUN_URL]/briefing/kr/morning" \
  --http-method=POST

# US 장중 5분마다 (ET 09:30~16:00 = KST 23:30~06:00)
gcloud scheduler jobs create http us-price-collect \
  --schedule="*/5 23-23,0-6 * * 1-5" \
  --time-zone="Asia/Seoul" \
  --uri="https://[CLOUD_RUN_URL]/collect/us/price" \
  --http-method=POST

# US 장전 브리핑 (22:00 KST)
gcloud scheduler jobs create http us-evening-briefing \
  --schedule="0 22 * * 1-5" \
  --time-zone="Asia/Seoul" \
  --uri="https://[CLOUD_RUN_URL]/briefing/us/evening" \
  --http-method=POST

# 장후 일일 정리 (KR 16:00, US 07:00 KST)
gcloud scheduler jobs create http kr-daily-close \
  --schedule="0 16 * * 1-5" \
  --time-zone="Asia/Seoul" \
  --uri="https://[CLOUD_RUN_URL]/daily/kr/close" \
  --http-method=POST
```

### Step 7: MongoDB Atlas M0 (Week 1)

1. https://cloud.mongodb.com 에서 무료 클러스터 생성
2. Provider: GCP, Region: Seoul (또는 Iowa)
3. Tier: M0 (무료, 512MB)
4. Network Access: GCP VM 및 Cloud Run IP 허용
5. `settings.local.yaml`에 connection string 입력

### Step 8: 서비스 계정 & IAM (Week 1)

```bash
# Cloud Run용 서비스 계정
gcloud iam service-accounts create stock-runner \
  --display-name="Stock Trading Runner"

# 필요 권한 부여
gcloud projects add-iam-policy-binding [PROJECT_ID] \
  --member="serviceAccount:stock-runner@[PROJECT_ID].iam.gserviceaccount.com" \
  --role="roles/bigquery.dataEditor"

gcloud projects add-iam-policy-binding [PROJECT_ID] \
  --member="serviceAccount:stock-runner@[PROJECT_ID].iam.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"
```

## 완료 기준

- [ ] BigQuery 데이터셋 생성 확인
- [ ] Cloud Storage 버킷 접근 확인
- [ ] e2-micro VM SSH 접속 + Redis 응답 확인
- [ ] Cloud Run 테스트 서비스 배포 + HTTP 응답 확인
- [ ] Cloud Scheduler → Cloud Run 트리거 정상 동작
- [ ] MongoDB Atlas 연결 확인
- [ ] 전체 월 비용 $0 확인 (GCP 결제 대시보드)

## 비용 모니터링

```bash
# 예산 알림 설정 ($1 초과 시 알림)
gcloud billing budgets create \
  --billing-account=[ACCOUNT_ID] \
  --display-name="Stock Trading Budget" \
  --budget-amount=1.00USD \
  --threshold-rule=percent=0.5 \
  --threshold-rule=percent=0.9 \
  --threshold-rule=percent=1.0
```

---

## Hybrid Update (2026-02-16)

### Cloud Functions 추가: 포지션 수동입력 페이지
- 목적: 사용자 보유종목(매수 단가/수량/매수일/계좌 구분) 수동 입력
- 배포: GCP Cloud Functions (HTTP) + Cloud Storage static hosting(또는 단일 함수 템플릿 렌더링)
- 인증: Google OAuth/IAP 중 택1

### 엔드포인트 계획
- `GET /portfolio/input` : 입력 UI 페이지 반환
- `POST /portfolio/input` : 보유 포지션 저장/수정
- `GET /portfolio/current` : 현재 입력된 포지션 조회
- `GET /recommendations/sell` : 보유 포지션 기준 매도 제안 조회

### 운영 규칙
- 24시간 이상 미갱신 포지션은 `stale` 상태로 표시
- stale 상태에서는 자동 실행 차단, 제안만 생성
- 모든 입력/수정 이벤트는 감사 로그에 기록
## Trade Ledger Update (2026-02-16)
### Cloud Functions 엔드포인트 확장
- `POST /portfolio/trades` : 매수/매도 체결 내역 수동 등록
- `GET /portfolio/holdings` : 원장 기반 현재 보유 포지션 조회

### 제약 조건
- `GET /recommendations/sell`는 내부적으로 `holdings` 집합을 먼저 계산한다.
- holdings에 없는 종목은 매도 제안 대상에서 제외한다.