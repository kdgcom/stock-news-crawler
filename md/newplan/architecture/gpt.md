# 통합 아키텍처 권고안 (GPT)

## 1) 4개 계획안 통합 요약
`codex/gpt`, `claude`, `gemini`, `cursor` 계획의 공통 분모는 아래 5가지다.

- KR/US 뉴스+시세 수집, 이벤트 표준화(`event_id`, UTC, 멱등 처리)
- 저장소 분리(원문/가공/시계열/캐시)
- 다중 신호 결합(뉴스/기술/체제) + 리스크 게이트 최종 승인
- 페이퍼 트레이딩 → 점진적 실거래 전환
- 감사로그/재현성/운영 모니터링을 필수 요건으로 설정

즉, 핵심은 "모델 성능보다 데이터 품질과 리스크 통제"다.

## 2) 클라우드 최종 추천: **GCP**

### 결론
5년 유지 + 비용 최적화 + 초기 트래픽 불확실성 조건에서는 **GCP를 1순위**로 권고한다.

### 이유
- 서버리스 무료 구간이 명확하고, 초기 MVP/저트래픽 구간 비용을 낮추기 쉽다.
- Cloud Run/Cloud Functions + Scheduler + Pub/Sub 조합으로 운영 자동화 구성이 단순하다.
- 향후 트래픽 증가 시 동일 아키텍처로 점진 확장(Cloud Run min instance, GKE, Memorystore, BigQuery) 가능하다.

### AWS/Azure 대비 판단
- AWS: 성숙하고 선택지는 가장 넓지만, 이 프로젝트 초반에는 운영 복잡도와 비용 관리 난이도가 상대적으로 높다.
- Azure: 엔터프라이즈 통합 강점이 크지만, 본 프로젝트 요구(뉴스 파이프라인+서버리스+장기 비용 절감)에서 GCP 대비 우위가 명확하지 않다.

## 3) DB 전략: **혼합 사용 권장 (RDB + NoSQL + Time-series)**

단일 DB로 해결하지 말고 역할 분리한다.

### RDB (필수)
- 용도: 계정, 포지션, 주문, 리스크 룰, 감사 메타데이터
- 권장: **Cloud SQL for PostgreSQL**
- 이유: 트랜잭션 정합성, 조인, 운영 표준성

### NoSQL (필수)
- 용도: 원문 뉴스/가공 뉴스 이벤트(JSON 문서), NER/토픽 결과
- 권장: **Firestore (Native mode)**
- 이유: 문서 구조 유연성, 이벤트 스키마 진화 용이

### Time-series (필수)
- 용도: 1분봉 OHLCV, 스프레드/변동성, 피처 이력, 백테스트 집계
- 권장 1순위: **BigQuery (partition + clustering + time-series SQL)**
- 권장 2순위: Cloud SQL(PostgreSQL) 파티셔닝 테이블(초기 소규모)

### 왜 TimescaleDB 단독이 아닌가?
- 기존 계획에는 TimescaleDB가 자주 등장하지만, GCP의 관리형 PostgreSQL(Cloud SQL)에서 Timescale 확장 사용 제약 이슈가 있어 5년 운영 리스크가 있다.
- 따라서 GCP에서는 "Cloud SQL + BigQuery" 조합이 장기적으로 더 안정적이다.

## 4) API 운영: **서버리스 우선, VM은 조건부**

### 권고안
- 기본: **Cloud Run + API Gateway(또는 HTTPS LB)**
- 배치/수집: **Cloud Scheduler → Pub/Sub → Cloud Run Job/Function**
- 큐/재시도: Pub/Sub + Cloud Tasks

### VM이 유리해지는 조건
아래 중 2개 이상 충족 시 VM/GKE 전환 검토
- 24시간 고정 고부하(상시 vCPU 사용률 높음)
- 냉시작(cold start)로 SLA 미달
- 장시간 stateful 워커/저지연 소켓 처리 비중 급증

## 5) "GCP 무료 호출 범위" 현실성 평가

### 가능
- API/함수 호출 자체는 월간 저~중트래픽에서는 무료/저비용 구간에 충분히 들어올 가능성이 높다.
- 예: MVP 단계에서 사용자 API + 내부 작업 호출이 월 수십만~100만대라면 서버리스 호출비는 매우 낮게 유지 가능.

### 불가능/주의
- **완전 무료 운영은 어려움**: 운영용 DB(Cloud SQL), Redis(Memorystore), 네트워크 egress가 비용을 만든다.
- 즉, "호출 무료"와 "서비스 전체 무료"는 다르다.

## 6) 5년 유지 관점의 최종 구조 (권고)

- Compute/API: Cloud Run
- Scheduler/Event: Cloud Scheduler + Pub/Sub + Cloud Tasks
- RDB: Cloud SQL(PostgreSQL)
- NoSQL: Firestore
- Time-series/Analytics: BigQuery
- Cache: Memorystore(Redis) - 트래픽 발생 후 단계적 도입
- Monitoring: Cloud Monitoring + Grafana(필요 시)
- IaC: Terraform (멀티클라우드 전환 여지 확보)

## 7) 실행 순서(현실적)

1. Phase 1(0~2개월): Cloud Run + Firestore + Cloud SQL 최소구성, 페이퍼 트레이딩 우선
2. Phase 2(3~6개월): BigQuery 시계열 분석 파이프라인, 리스크 게이트 고도화
3. Phase 3(6~12개월): 비용 모니터링(FinOps), 캐시/큐 최적화
4. Phase 4(1년+): 실거래 확장, 지역 이중화/DR, 모델 운영 자동화(champion/challenger)

## 8) 최종 의사결정

- **클라우드**: GCP
- **DB**: RDB + NoSQL + Time-series 혼합
  - RDB: Cloud SQL(PostgreSQL)
  - NoSQL: Firestore
  - Time-series: BigQuery(주), Cloud SQL(보조)
- **API 런타임**: 서버리스 우선(Cloud Run), VM은 조건부 전환

---

## 근거 링크 (공식 문서 중심)
- GCP Cloud Run pricing/free tier: https://cloud.google.com/run/pricing
- GCP Cloud Functions pricing/free tier: https://cloud.google.com/functions/pricing-1stgen
- GCP Scheduler pricing (free jobs): https://cloud.google.com/scheduler/pricing
- GCP Cloud Tasks pricing (free tier): https://cloud.google.com/tasks/pricing
- GCP BigQuery time-series functions: https://cloud.google.com/bigquery/docs/reference/standard-sql/time-series-functions
- GCP Cloud SQL pricing: https://cloud.google.com/sql/pricing
- AWS Lambda pricing/free tier: https://aws.amazon.com/lambda/pricing/
- AWS API Gateway pricing/free tier: https://aws.amazon.com/api-gateway/pricing/
- Azure Functions pricing: https://azure.microsoft.com/en-us/pricing/details/functions/
- Azure Database for PostgreSQL supported extensions: https://learn.microsoft.com/en-us/azure/postgresql/extensions/concepts-extensions-considerations
- AWS RDS PostgreSQL extension versions: https://docs.aws.amazon.com/AmazonRDS/latest/PostgreSQLReleaseNotes/postgresql-extensions.html
