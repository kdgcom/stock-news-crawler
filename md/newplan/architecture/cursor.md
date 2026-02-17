# 클라우드·DB·API 아키텍처 분석 (Cursor)

> 4개 LLM 계획(codex, claude, gemini, cursor)을 종합하여 클라우드·DB·API 전략을 분석한 결과

---

## 1. 4개 계획안 통합 요약

### 1.1 공통 아키텍처

| 계층 | codex | claude | gemini | cursor |
|------|-------|--------|--------|--------|
| Collection | KR/US 뉴스·시세·공시 | 동일 + DART/SEC | 동일 | 동일 |
| Streaming | Redis Streams | Redis Streams | Redis/Kafka | Redis Streams |
| Storage | MongoDB, TimescaleDB, Redis | 동일 | S3/MinIO, TimescaleDB, MongoDB, Redis | 동일 |
| Analysis | 규칙→LightGBM | Multi-Agent, KoBERT/FinBERT | Agent A/B/C | 동일 |
| Risk | 하드리밋, 킬스위치 | 3계층 리스크 | 독립 Risk Gate | 동일 |
| Execution | Paper → Broker | 동일 | 동일 | 동일 |

### 1.2 핵심 요구사항

- **데이터**: event_id 멱등, UTC 저장, event-time/ingest-time 분리
- **저장소**: 원문(raw) + 가공(enriched) 분리, 시계열 전용 저장소
- **리스크**: 독립 Risk Gate, 모든 거래 최종 검증
- **운영**: 5년 유지, 비용 최적화, 점진적 확장

---

## 2. 클라우드 추천: **GCP (1순위)**

### 2.1 최종 결론

| 순위 | 클라우드 | 적합도 | 핵심 사유 |
|------|----------|--------|-----------|
| **1** | **GCP** | ★★★★★ | 무료 티어 명확, 서버리스 비용 최소, 5년 CUD 활용 |
| 2 | AWS | ★★★★☆ | 성숙도 높으나 초기 복잡도·비용 |
| 3 | Azure | ★★★☆☆ | 엔터프라이즈 강점, 본 프로젝트 대비 우위 불명확 |

### 2.2 GCP 추천 이유

#### (1) 5년 유지 관점

- **Committed Use Discounts (CUD)**: 1년/3년 약정 시 vCPU·메모리 최대 72% 할인
- Cloud Run, Compute Engine, GKE에 CUD 적용 가능 → 장기 비용 예측 가능
- BigQuery, Cloud SQL 등 관리형 서비스 5년 지원 안정적

#### (2) 비용 비교 (2024~2025 기준)

| 항목 | GCP | AWS | Azure |
|------|-----|-----|-------|
| vCPU 시간당 | ~$0.038 | ~$0.0416 | ~$0.04 |
| Cloud Run/Lambda | 2M 요청 무료 | 1M 무료 | 1M 무료 |
| MongoDB Atlas (1TB) | ~$180/월 | ~$200/월 | ~$220/월 |
| 5년 TCO (소규모) | 가장 낮은 편 | 중간 | 중간~높음 |

- GCP는 per-second 과금으로 저부하 시 유리
- 소규모 프로젝트에서 5년 누적 시 10~30% 수준 비용 차이 가능

#### (3) 서버리스 무료 티어 (GCP)

| 서비스 | 무료 범위 (월) | 비고 |
|--------|----------------|------|
| Cloud Run (요청 기반) | 2M 요청, 180K vCPU초, 360K GiB초 | us-central1 등 Tier 1 리전 |
| Cloud Run Jobs | 450K GiB초, 240K vCPU초 | 배치·스케줄 작업 |
| Cloud Scheduler | 3개 작업 무료 | cron 트리거 |
| Cloud Pub/Sub | 10GB 무료 | 이벤트 버스 |
| Cloud Functions (1세대) | 2M 호출 무료 | 레거시 |

---

## 3. DB 전략: **혼합 사용 (RDB + NoSQL + Time-series)**

### 3.1 역할 분리

단일 DB로 해결하지 않고, 데이터 특성에 맞게 분리한다.

| 유형 | 용도 | 권장 제품 | 근거 |
|------|------|-----------|------|
| **RDB** | 계정, 포지션, 주문, 리스크 룰, decision_log 메타 | PostgreSQL (Cloud SQL) | 트랜잭션, 조인, 감사 추적 |
| **NoSQL** | raw_news_events, enriched_news_events | MongoDB | 문서 스키마 유연, event_id upsert |
| **Time-series** | market_1m_bars, OHLCV, 변동성 | TimescaleDB 또는 BigQuery | 시계열 쿼리, 압축, 파티션 |
| **Cache** | Redis Streams, 실시간 상태, 저지연 캐시 | Redis (Memorystore) | 이벤트 버스, 세션 |

### 3.2 GCP 환경에서의 구체적 선택

| DB | GCP 옵션 | 비고 |
|----|----------|------|
| RDB | **Cloud SQL for PostgreSQL** | 표준, 확장·백업 관리 용이 |
| NoSQL | **Firestore** 또는 **MongoDB Atlas (GCP)** | Firestore: GCP 네이티브, MongoDB: 기존 계획과 일치 |
| Time-series | **BigQuery** (주) 또는 **Cloud SQL + TimescaleDB** | BigQuery: 대용량·분석, TimescaleDB: 실시간 쿼리 |
| Cache | **Memorystore for Redis** | VPC 내 저지연 |

### 3.3 TimescaleDB vs BigQuery

| 기준 | TimescaleDB | BigQuery |
|------|-------------|----------|
| 실시간 쿼리 | 우수 | 배치·분석 중심 |
| 1분봉 실시간 저장 | 적합 | 스트리밍 삽입 지원하나 비용 |
| 백테스트·집계 | 가능 | 매우 우수 |
| GCP 관리형 | Cloud SQL 확장 제한 가능 | 네이티브 |
| 5년 운영 | 셀프 호스팅 시 유지보수 부담 | 관리형으로 안정 |

**권고**: Phase 1~2는 **Cloud SQL(PostgreSQL) + 파티셔닝**으로 시계열 저장, Phase 3+에서 **BigQuery**로 분석·백테스트 이관 검토.

---

## 4. API: **서버리스 우선, VM은 조건부**

### 4.1 결론

| 워크로드 | 권장 | 이유 |
|----------|------|------|
| API (추천·신호 조회) | **Cloud Run** | 저트래픽 시 무료, 스케일 0 가능 |
| 뉴스·시세 수집 (스케줄) | **Cloud Run Jobs** | 호출 시에만 과금, 무료 범위 내 가능 |
| 이벤트 버스 | **Pub/Sub** | 10GB/월 무료 |
| 장시간·고부하 배치 | VM 또는 GKE | 15분 초과, 상시 고부하 시 |

### 4.2 서버리스 vs VM 비교

| 기준 | 서버리스 (Cloud Run) | VM (Compute Engine) |
|------|----------------------|----------------------|
| 저트래픽 (<100K/월) | **매우 유리** (무료~저비용) | 24시간 과금으로 비효율 |
| 스케줄 작업 (시간당 1회) | **유리** (실행 시간만 과금) | 상시 가동 비용 |
| 15분 초과 작업 | 제한 | 적합 |
| Cold start | 1~3초 수준 | 없음 |
| 5년 CUD | Cloud Run CUD 적용 가능 | Compute Engine CUD 적용 |

### 4.3 GCP 무료 범위 내 서비스 구현 가능성

#### 가능한 시나리오 (1달 무료·저비용)

| 구성요소 | 월 호출/사용량 | 무료 범위 | 판정 |
|----------|----------------|-----------|------|
| API (추천 조회) | ~50K 요청 | 2M 요청 | ✅ 가능 |
| 뉴스 수집 (시간당 1회) | ~720 Job 실행 | 450K GiB초 | ✅ 가능 |
| 시세 수집 (5분마다) | ~8.6K Job 실행 | 동일 | ✅ 가능 |
| Pub/Sub 이벤트 | ~1GB | 10GB | ✅ 가능 |

#### 불가능·주의 사항

| 항목 | 내용 |
|------|------|
| **완전 무료 불가** | Cloud SQL, Memorystore, 네트워크 egress는 별도 과금 |
| **1분봉 전 종목** | KR+US 수천 종목 × 1분 = 호출량 급증 → 무료 범위 초과 가능 |
| **실시간 WebSocket** | Cloud Run은 요청-응답 중심, 장시간 연결은 VM/ GKE 고려 |

#### MVP Phase 1 무료·저비용 전략

1. **수집**: 관심 종목 100~500개로 제한, 5분봉 또는 1시간봉으로 완화
2. **API**: min instance 0, 요청 시에만 인스턴스 기동
3. **DB**: Firestore 무료 할당량(1GB)·Cloud SQL micro 활용
4. **예상 월 비용**: $20~50 수준 (DB·네트워크 중심)

---

## 5. 5년 유지 관점 최종 아키텍처

### 5.1 권고 스택 (GCP)

```
[Compute / API]
  Cloud Run (API, 서버리스)
  Cloud Run Jobs (수집·배치)
  Cloud Scheduler + Pub/Sub (트리거)

[Storage]
  Cloud SQL (PostgreSQL) — RDB, decision_log, 메타
  Firestore 또는 MongoDB Atlas — 뉴스 이벤트
  BigQuery — 시계열 분석·백테스트 (Phase 2+)
  Memorystore (Redis) — 캐시·스트림 (Phase 2+)

[Monitoring]
  Cloud Monitoring + Grafana (선택)
  Slack/Telegram 알림
```

### 5.2 단계별 도입

| Phase | 기간 | 구성 | 비용 목표 |
|-------|------|------|-----------|
| 1 | 0~2개월 | Cloud Run + Firestore + Cloud SQL 최소 | $20~50/월 |
| 2 | 3~6개월 | BigQuery, Memorystore, 리스크 게이트 | $50~150/월 |
| 3 | 6~12개월 | FinOps, 캐시·큐 최적화 | $100~200/월 |
| 4 | 1년+ | 실거래, CUD 1~3년 약정 | $150~300/월 |

### 5.3 IaC 및 멀티클라우드

- **Terraform** 사용 권고: GCP 고정이 아닌 경우 Azure/AWS 전환 여지 확보
- DB·스키마는 클라우드 중립 설계 유지

---

## 6. 최종 의사결정 요약

| 항목 | 결정 |
|------|------|
| **클라우드** | **GCP** (5년 유지·비용·서버리스 무료 티어) |
| **DB** | RDB + NoSQL + Time-series 혼합 |
| | RDB: Cloud SQL (PostgreSQL) |
| | NoSQL: Firestore 또는 MongoDB Atlas |
| | Time-series: Cloud SQL 파티션 → BigQuery (Phase 2+) |
| | Cache: Memorystore (Redis) |
| **API** | **서버리스 우선** (Cloud Run), VM은 고부하·장시간 작업 시 |
| **무료 범위** | MVP Phase 1은 1달 무료·저비용 구현 가능 (호출 제한·종목 수 제한 시) |

---

## 7. 근거 링크

- [GCP Cloud Run Pricing / Free Tier](https://cloud.google.com/run/pricing)
- [GCP Cloud Functions Pricing](https://cloud.google.com/functions/pricing-1stgen)
- [GCP Cloud Scheduler Pricing](https://cloud.google.com/scheduler/pricing)
- [GCP Committed Use Discounts](https://cloud.google.com/docs/cuds)
- [AWS vs Azure vs GCP Pricing 2024](https://devhunt.org/blog/aws-vs-azure-vs-gcp-cloud-pricing-comparison-2024)
- [Serverless vs VM Cost (Low Traffic)](https://castanedanetworks.com/blog/ec2-vs-serverless-cost-analysis/)
