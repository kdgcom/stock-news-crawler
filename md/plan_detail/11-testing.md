# 11. 테스트 전략

> 전 Phase 공통 | 각 Track과 병렬 진행 | 소요: 지속적

## 테스트 원칙

1. **모든 모듈은 단위 테스트 없이 머지하지 않는다**
2. **외부 의존성(API, DB, Redis)은 반드시 Mock/Fake로 대체한다**
3. **리스크 관련 로직은 경계값 테스트를 필수로 포함한다**
4. **Paper Trading 전환 전 통합 테스트 통과를 전제한다**

## 프레임워크 & 도구

| 도구 | 용도 | 설치 |
|------|------|------|
| `pytest` | 테스트 실행기 | `pip install pytest` |
| `pytest-cov` | 커버리지 측정 | `pip install pytest-cov` |
| `pytest-asyncio` | 비동기 테스트 | `pip install pytest-asyncio` |
| `pytest-mock` | Mock/Patch | `pip install pytest-mock` |
| `freezegun` | 시간 고정 (장전 루틴 등) | `pip install freezegun` |
| `responses` / `respx` | HTTP Mock (sync/async) | `pip install respx` |
| `fakeredis` | Redis Mock | `pip install fakeredis` |
| `testcontainers` | MongoDB 통합 테스트 | `pip install testcontainers` |

## 디렉토리 구조

```
tests/
├── conftest.py                  ← 공통 fixture (설정, DB mock, Redis mock)
├── unit/                        ← 단위 테스트 (외부 의존 0)
│   ├── test_config.py
│   ├── collection/
│   │   ├── test_naver_adapter.py
│   │   ├── test_alpaca_adapter.py
│   │   ├── test_news_normalizer.py
│   │   └── test_dedup.py
│   ├── storage/
│   │   ├── test_bigquery_loader.py
│   │   ├── test_mongodb_writer.py
│   │   └── test_redis_cache.py
│   ├── analysis/
│   │   ├── test_sentiment_momentum.py
│   │   ├── test_technical_trend.py
│   │   ├── test_mean_reversion.py
│   │   ├── test_event_catalyst.py
│   │   ├── test_algorithm_router.py
│   │   ├── test_ensemble_runner.py
│   │   └── test_hybrid_fusion.py
│   ├── langgraph/
│   │   ├── test_analysis_graph.py
│   │   ├── test_briefing_graph.py
│   │   ├── test_sell_approval_graph.py
│   │   ├── test_agent_nodes.py
│   │   └── test_checkpoint_recovery.py
│   ├── risk/
│   │   ├── test_hard_limits.py
│   │   ├── test_dynamic_risk.py
│   │   ├── test_kill_switch.py
│   │   └── test_stop_loss.py
│   ├── execution/
│   │   ├── test_paper_executor.py
│   │   ├── test_position_manager.py
│   │   └── test_trade_ledger.py
│   ├── universe/
│   │   ├── test_tier_selection.py
│   │   ├── test_promotion.py
│   │   └── test_demotion.py
│   └── portfolio/
│       ├── test_holdings_input.py
│       └── test_sell_recommendation.py
├── integration/                 ← 통합 테스트 (실제 DB 연결)
│   ├── test_collection_pipeline.py
│   ├── test_storage_pipeline.py
│   ├── test_analysis_pipeline.py
│   ├── test_execution_pipeline.py
│   └── test_portfolio_api.py
├── e2e/                         ← 종단간 테스트
│   ├── test_kr_morning_routine.py
│   ├── test_us_evening_routine.py
│   ├── test_signal_to_paper_trade.py
│   ├── test_sell_recommendation_flow.py
│   └── test_langgraph_sell_approval_e2e.py
└── fixtures/                    ← 테스트 데이터
    ├── news_samples/
    │   ├── kr_positive.json
    │   ├── kr_negative.json
    │   ├── us_earnings.json
    │   └── us_fda_approval.json
    ├── price_samples/
    │   ├── kr_5min_bars.json
    │   └── us_5min_bars.json
    ├── signals/
    │   ├── buy_signal.json
    │   ├── sell_signal.json
    │   └── hold_signal.json
    └── portfolio/
        ├── sample_holdings.json
        └── sample_trade_ledger.json
```

## 테스트 레벨별 상세

### Level 1: 단위 테스트 (Unit)

외부 의존성 없이 함수/클래스 단위로 검증한다.

#### 데이터 수집 (03-data-collection)

```python
# tests/unit/collection/test_news_normalizer.py

class TestNewsNormalizer:
    """뉴스 정규화 로직 검증"""

    def test_naver_news_normalize(self, sample_naver_raw):
        """네이버 금융 뉴스 → 표준 포맷 변환"""
        result = normalize_news(sample_naver_raw, source="naver")
        assert result["source"] == "naver"
        assert result["market"] == "KR"
        assert "title" in result
        assert "published_at" in result
        assert isinstance(result["published_at"], datetime)

    def test_alpaca_news_normalize(self, sample_alpaca_raw):
        """Alpaca 뉴스 → 표준 포맷 변환"""
        result = normalize_news(sample_alpaca_raw, source="alpaca")
        assert result["source"] == "alpaca"
        assert result["market"] == "US"
        assert len(result["symbols"]) > 0

    def test_duplicate_detection(self):
        """동일 뉴스 중복 감지"""
        news_a = {"title": "삼성전자 HBM4 양산", "url": "https://..."}
        news_b = {"title": "삼성전자 HBM4 양산 계획", "url": "https://..."}
        assert is_duplicate(news_a, news_b, threshold=0.85) is True

    def test_empty_article_rejected(self):
        """본문 없는 기사 거부"""
        with pytest.raises(ValidationError):
            normalize_news({"title": "", "content": ""}, source="naver")
```

#### 분석 엔진 (06-analysis-engine)

```python
# tests/unit/analysis/test_sentiment_momentum.py

class TestSentimentMomentum:
    """SM 알고리즘 단위 테스트"""

    def test_strong_positive_signal(self, positive_context):
        """강한 긍정 감성 → BUY 신호"""
        algo = SentimentMomentumAlgorithm(config)
        signal = algo.analyze(positive_context)
        assert signal.decision == "BUY"
        assert signal.score > 0.6

    def test_strong_negative_signal(self, negative_context):
        """강한 부정 감성 → SELL 신호"""
        algo = SentimentMomentumAlgorithm(config)
        signal = algo.analyze(negative_context)
        assert signal.decision == "SELL"
        assert signal.score < -0.6

    def test_no_news_returns_hold(self, empty_news_context):
        """뉴스 없으면 HOLD"""
        algo = SentimentMomentumAlgorithm(config)
        signal = algo.analyze(empty_news_context)
        assert signal.decision == "HOLD"
        assert signal.confidence < 0.3

    def test_score_within_bounds(self, random_context):
        """점수가 항상 [-1, 1] 범위"""
        algo = SentimentMomentumAlgorithm(config)
        signal = algo.analyze(random_context)
        assert -1.0 <= signal.score <= 1.0
```

```python
# tests/unit/analysis/test_hybrid_fusion.py

class TestHybridFusion:
    """Hybrid 의사결정 융합 테스트"""

    def test_alpha_blending_default(self):
        """기본 alpha=0.7 적용"""
        result = fuse_scores(numeric=0.8, agent=0.6, alpha=0.7)
        expected = 0.7 * 0.8 + 0.3 * 0.6  # 0.74
        assert abs(result - expected) < 1e-6

    def test_agent_timeout_fallback(self):
        """Agent 타임아웃 시 수치 엔진만 사용"""
        result = fuse_scores(numeric=0.8, agent=None, alpha=0.7)
        assert result == 0.8

    def test_volatile_alpha_adjustment(self):
        """변동성 구간 alpha 자동 하향"""
        alpha = compute_dynamic_alpha(vix=30, default=0.7)
        assert alpha < 0.7  # 변동성 높으면 agent 비중 증가
```

#### LangGraph 그래프 테스트

```python
# tests/unit/langgraph/test_analysis_graph.py

class TestAnalysisGraph:
    """AnalysisGraph StateGraph 단위 테스트"""

    def test_numeric_only_path(self, mock_llm, config):
        """Agent 불필요 시 numeric → trigger → fusion → decision (Agent 건너뜀)"""
        graph = build_analysis_graph()
        result = graph.invoke({
            "symbol": "005930",
            "market": "KR",
            "context": serialize_context(neutral_context),  # Agent 트리거 안됨
            "errors": [],
        })
        assert result["agent_required"] is False
        assert result["agent_score"] is None
        assert result["final_score"] == result["numeric_score"]  # alpha=1.0

    def test_agent_fan_out_path(self, mock_llm, config):
        """Agent 필요 시 4종 Agent 병렬 실행 + fusion"""
        graph = build_analysis_graph()
        result = graph.invoke({
            "symbol": "005930",
            "market": "KR",
            "context": serialize_context(ambiguous_context),  # 임계값 근접
            "errors": [],
        })
        assert result["agent_required"] is True
        assert result["agent_news_result"] is not None
        assert result["alpha"] < 1.0
        assert result["final_score"] != result["numeric_score"]

    def test_all_agents_fail_fallback(self, failing_llm, config):
        """모든 Agent 실패 → numeric_only 폴백"""
        graph = build_analysis_graph()
        result = graph.invoke({
            "symbol": "005930",
            "market": "KR",
            "context": serialize_context(ambiguous_context),
            "errors": [],
        })
        assert result["agent_required"] is True
        assert result["agent_score"] is None
        assert "ALL_AGENTS_FAILED" in result["errors"]
        assert result["final_score"] == result["numeric_score"]

    def test_checkpoint_recovery(self, mock_llm, config, tmp_path):
        """체크포인트에서 중간 노드부터 재개"""
        checkpointer = SqliteSaver.from_conn_string(f"{tmp_path}/test.db")
        graph = build_analysis_graph_with(checkpointer)
        thread = {"configurable": {"thread_id": "test-recovery"}}

        # 1차 실행 (trigger까지만 진행 가정)
        state_after_trigger = get_checkpoint(checkpointer, thread)
        assert state_after_trigger["numeric_score"] is not None
```

```python
# tests/unit/langgraph/test_sell_approval_graph.py

class TestSellApprovalGraph:
    """SellApprovalGraph Human-in-the-loop 테스트"""

    def test_interrupt_and_resume_approve(self, config, tmp_path):
        """interrupt → APPROVE resume → execute → ledger"""
        graph = build_sell_approval_graph()
        thread = {"configurable": {"thread_id": "test-sell-1"}}

        # 시작 (interrupt에서 멈춤)
        result = graph.invoke({
            "recommendation_id": "rec-001",
            "symbol": "005930",
            "market": "KR",
            "action": "SELL",
            "target_quantity": 50,
            "errors": [],
        }, config=thread)

        # interrupt 상태 확인
        state = graph.get_state(thread)
        assert state.next == ("wait_approval",)

        # resume (승인)
        result = graph.invoke(
            Command(resume={"decision": "APPROVE"}),
            config=thread,
        )
        assert result["execution_result"]["status"] == "FILLED"
        assert result["ledger_recorded"] is True

    def test_interrupt_and_resume_reject(self, config, tmp_path):
        """interrupt → REJECT resume → END (실행 없음)"""
        graph = build_sell_approval_graph()
        thread = {"configurable": {"thread_id": "test-sell-2"}}

        graph.invoke(sell_input, config=thread)
        result = graph.invoke(
            Command(resume={"decision": "REJECT"}),
            config=thread,
        )
        assert result["execution_result"] is None
        assert result["ledger_recorded"] is False

    def test_no_position_blocks_early(self, config):
        """미보유 종목 → validate에서 차단, interrupt 도달 안 함"""
        graph = build_sell_approval_graph()
        result = graph.invoke({
            "symbol": "999999",  # 미보유
            "target_quantity": 10,
            "errors": [],
        })
        assert result["holding_valid"] is False
        assert result["user_notified"] is False

    def test_timeout_expiry(self, config, tmp_path):
        """48시간 미승인 → TIMEOUT resume → END"""
        graph = build_sell_approval_graph()
        thread = {"configurable": {"thread_id": "test-sell-timeout"}}

        graph.invoke(sell_input, config=thread)
        result = graph.invoke(
            Command(resume={"decision": "TIMEOUT"}),
            config=thread,
        )
        assert result["expired"] is True or result["user_decision"] == "TIMEOUT"
```

```python
# tests/unit/langgraph/test_briefing_graph.py

class TestBriefingGraph:
    """BriefingGraph 파이프라인 테스트"""

    def test_full_briefing_pipeline(self, mock_apis, mock_llm):
        """전체 수집 → 분석 → 브리핑 → 발송 정상 흐름"""
        graph = build_briefing_graph()
        result = graph.invoke({
            "market": "KR",
            "run_date": "2026-02-17",
            "errors": [],
        })
        assert result["briefing_text"] != ""
        assert result["briefing_sent"] is True
        assert len(result["errors"]) == 0

    def test_partial_failure_still_generates(self, mock_apis_partial, mock_llm):
        """DART 수집 실패 → 나머지로 부분 브리핑 생성"""
        graph = build_briefing_graph()
        result = graph.invoke({
            "market": "KR",
            "run_date": "2026-02-17",
            "errors": [],
        })
        assert result["dart_data"] is None
        assert "DART_FAIL" in result["errors"]
        assert result["briefing_text"] != ""  # 부분 브리핑 생성됨
        assert result["briefing_sent"] is True
```

#### 리스크 관리 (07-risk-management)

```python
# tests/unit/risk/test_hard_limits.py

class TestHardLimits:
    """하드 리밋 경계값 테스트"""

    def test_daily_loss_within_limit(self):
        """일일 손실 한도 이내 → 통과"""
        portfolio = {"daily_pnl_pct": -0.02}  # -2%
        ok, reason = check_hard_limits(portfolio, max_daily_loss=-0.03)
        assert ok is True

    def test_daily_loss_exceeds_limit(self):
        """일일 손실 한도 초과 → 차단"""
        portfolio = {"daily_pnl_pct": -0.035}  # -3.5%
        ok, reason = check_hard_limits(portfolio, max_daily_loss=-0.03)
        assert ok is False
        assert reason == "DAILY_LOSS_EXCEEDED"

    def test_max_positions_limit(self):
        """최대 종목 수 초과 → 신규 매수 차단"""
        portfolio = {"open_positions": 10}
        ok, reason = check_hard_limits(portfolio, max_positions=10)
        assert ok is False
        assert reason == "MAX_POSITIONS_REACHED"

    def test_single_position_size_limit(self):
        """단일 종목 비중 초과 → 차단"""
        signal = {"symbol": "005930", "size_pct": 0.12}  # 12%
        ok, reason = check_position_size(signal, max_single_pct=0.10)
        assert ok is False
        assert reason == "POSITION_SIZE_EXCEEDED"
```

```python
# tests/unit/risk/test_kill_switch.py

class TestKillSwitch:
    """Kill Switch 테스트"""

    def test_kill_switch_activates_on_loss(self):
        """일일 손실 한도 초과 시 활성화"""
        ks = KillSwitch(config)
        ks.check(daily_pnl_pct=-0.035)
        assert ks.is_active() is True

    def test_kill_switch_blocks_new_orders(self):
        """활성화 후 모든 신규 주문 차단"""
        ks = KillSwitch(config)
        ks.activate("DAILY_LOSS_EXCEEDED")
        signal = {"decision": "BUY", "symbol": "005930"}
        result = ks.gate(signal)
        assert result["status"] == "BLOCKED"
        assert result["reason"] == "KILL_SWITCH"

    def test_kill_switch_requires_manual_reset(self):
        """수동 해제 전까지 유지"""
        ks = KillSwitch(config)
        ks.activate("DAILY_LOSS_EXCEEDED")
        # 다음 날이 되어도 자동 해제 안됨
        assert ks.is_active() is True

    def test_kill_switch_manual_reset(self):
        """수동 해제 정상 동작"""
        ks = KillSwitch(config)
        ks.activate("DAILY_LOSS_EXCEEDED")
        ks.reset(confirmed_by="admin")
        assert ks.is_active() is False
```

#### 매매 실행 (08-execution)

```python
# tests/unit/execution/test_trade_ledger.py

class TestTradeLedger:
    """거래 원장 테스트"""

    def test_buy_records_positive_quantity(self):
        """매수 기록 → quantity > 0"""
        entry = create_ledger_entry(side="BUY", symbol="005930", quantity=100, price=58200)
        assert entry["side"] == "BUY"
        assert entry["quantity"] == 100

    def test_sell_records_positive_quantity(self):
        """매도 기록"""
        entry = create_ledger_entry(side="SELL", symbol="005930", quantity=50, price=59000)
        assert entry["side"] == "SELL"
        assert entry["quantity"] == 50

    def test_net_quantity_calculation(self, sample_ledger):
        """순보유 수량 = SUM(BUY) - SUM(SELL)"""
        # BUY 100 + BUY 50 - SELL 30 = 120
        net = calculate_net_quantity(sample_ledger, symbol="005930")
        assert net == 120

    def test_sell_blocked_when_no_position(self):
        """미보유 종목 매도 차단"""
        ledger = []  # 빈 원장
        with pytest.raises(NoOpenPositionError):
            validate_sell(ledger, symbol="005930", quantity=10)

    def test_oversell_blocked(self, sample_ledger):
        """보유 수량 초과 매도 차단"""
        # net_quantity = 120
        with pytest.raises(OversellError):
            validate_sell(sample_ledger, symbol="005930", quantity=150)
```

#### 포트폴리오 입력 (Hybrid Update)

```python
# tests/unit/portfolio/test_sell_recommendation.py

class TestSellRecommendation:
    """매도 제안 로직 테스트"""

    def test_only_held_stocks_get_recommendations(self):
        """보유 종목만 매도 제안 대상"""
        holdings = {"005930": 100, "000660": 50}
        universe = ["005930", "000660", "035420", "051910"]
        targets = filter_sell_targets(universe, holdings)
        assert set(targets) == {"005930", "000660"}
        assert "035420" not in targets  # 미보유

    def test_zero_quantity_excluded(self):
        """net_quantity = 0인 종목 제외"""
        holdings = {"005930": 0, "000660": 50}
        targets = filter_sell_targets(["005930", "000660"], holdings)
        assert "005930" not in targets

    def test_recommendation_requires_confirmation(self):
        """매도 제안은 사용자 확인 필수"""
        rec = generate_sell_recommendation("005930", score=-0.7)
        assert rec["auto_execute"] is False
        assert rec["requires_confirmation"] is True
```

### Level 2: 통합 테스트 (Integration)

실제 DB 연결이 필요한 파이프라인 테스트. 로컬 또는 테스트 환경에서 실행.

```python
# tests/integration/test_collection_pipeline.py

@pytest.mark.integration
class TestCollectionPipeline:
    """수집 → 저장 파이프라인 통합 테스트"""

    @pytest.fixture
    def mongo_client(self):
        """테스트용 MongoDB 연결 (testcontainers 사용)"""
        with MongoContainer() as mongo:
            yield pymongo.MongoClient(mongo.get_connection_url())

    def test_news_collect_and_store(self, mongo_client, mock_naver_api):
        """뉴스 수집 → MongoDB 저장 전체 흐름"""
        collector = NaverNewsCollector(config)
        articles = collector.collect(symbol="005930")
        assert len(articles) > 0

        writer = MongoDBWriter(mongo_client)
        writer.insert_news(articles)

        stored = mongo_client.stock_news.news_articles.count_documents({})
        assert stored == len(articles)

    def test_price_collect_and_cache(self, fake_redis, mock_kis_api):
        """시세 수집 → Redis 캐시 + BigQuery 배치 버퍼"""
        collector = KRPriceCollector(config)
        bars = collector.collect(symbols=["005930", "000660"])
        assert len(bars) == 2

        cache = RedisCache(fake_redis)
        for bar in bars:
            cache.set_price(bar)

        cached = cache.get_price("005930")
        assert cached is not None
```

```python
# tests/integration/test_portfolio_api.py

@pytest.mark.integration
class TestPortfolioAPI:
    """포트폴리오 입력 API 통합 테스트"""

    def test_input_holdings(self, test_client, fake_bq):
        """보유종목 입력 → BigQuery 저장"""
        response = test_client.post("/portfolio/input", json={
            "symbol": "005930",
            "market": "KR",
            "quantity": 100,
            "avg_cost": 58200,
            "bought_at": "2026-02-10",
        })
        assert response.status_code == 200

        rows = fake_bq.query("SELECT * FROM manual_holdings_lots WHERE symbol='005930'")
        assert len(rows) == 1

    def test_get_sell_recommendations(self, test_client, seeded_holdings):
        """보유종목 기반 매도 제안 조회"""
        response = test_client.get("/recommendations/sell")
        assert response.status_code == 200
        recs = response.json()
        # 보유 종목만 포함
        for rec in recs:
            assert rec["symbol"] in seeded_holdings
```

### Level 3: 종단간 테스트 (E2E)

실제 운영 시나리오를 시뮬레이션.

```python
# tests/e2e/test_signal_to_paper_trade.py

@pytest.mark.e2e
class TestSignalToPaperTrade:
    """신호 생성 → Paper 체결 전체 흐름"""

    def test_buy_signal_executes_paper_trade(self, full_system):
        """BUY 신호 → 리스크 게이트 → Paper 체결 → 포지션 생성"""
        # 1. 긍정 뉴스 + 기술 지표 투입
        inject_positive_scenario(full_system, symbol="005930")

        # 2. 분석 엔진 실행
        signal = full_system.analysis_engine.run("005930", market="KR")
        assert signal.decision == "BUY"

        # 3. 리스크 게이트 통과
        risk_ok, _ = full_system.risk_gate.check(signal)
        assert risk_ok is True

        # 4. Paper 체결
        result = full_system.paper_executor.execute(signal)
        assert result["status"] == "FILLED"

        # 5. 포지션 확인
        position = full_system.position_manager.get("KR", "005930")
        assert position is not None
        assert position["quantity"] > 0

        # 6. 거래 원장 기록 확인
        ledger = full_system.trade_ledger.query("005930")
        assert len(ledger) == 1
        assert ledger[0]["side"] == "BUY"
```

```python
# tests/e2e/test_sell_recommendation_flow.py

@pytest.mark.e2e
class TestSellRecommendationFlow:
    """보유종목 매도 제안 전체 흐름"""

    def test_full_sell_recommendation_cycle(self, full_system):
        """보유입력 → 분석 → 매도 제안 → 승인 → 체결"""
        # 1. 수동 보유 입력
        full_system.portfolio_api.input_holding(
            symbol="005930", quantity=100, avg_cost=58200
        )

        # 2. 부정적 시나리오 투입
        inject_negative_scenario(full_system, symbol="005930")

        # 3. 매도 제안 생성
        recs = full_system.sell_recommender.generate(market="KR")
        sell_rec = next(r for r in recs if r["symbol"] == "005930")
        assert sell_rec["action"] in ["SELL", "REDUCE"]
        assert sell_rec["requires_confirmation"] is True

        # 4. 사용자 승인
        full_system.portfolio_api.approve_recommendation(sell_rec["id"])

        # 5. 리스크 게이트 + 실행
        result = full_system.paper_executor.execute_approved(sell_rec)
        assert result["status"] == "FILLED"

        # 6. 원장 확인
        ledger = full_system.trade_ledger.query("005930")
        sells = [e for e in ledger if e["side"] == "SELL"]
        assert len(sells) == 1
```

## 공통 Fixture

```python
# tests/conftest.py

import pytest
from unittest.mock import MagicMock
import fakeredis

@pytest.fixture
def config():
    """테스트용 설정 (settings.yaml 기반, 민감 정보 제거)"""
    return load_config("config/settings.test.yaml")

@pytest.fixture
def fake_redis():
    """fakeredis 인스턴스"""
    return fakeredis.FakeRedis(decode_responses=True)

@pytest.fixture
def mock_llm():
    """LLM API Mock (비용 방지)"""
    llm = MagicMock()
    llm.analyze.return_value = {"sentiment": 0.5, "confidence": 0.8}
    return llm

@pytest.fixture
def sample_naver_raw():
    """네이버 뉴스 원본 샘플"""
    return load_fixture("news_samples/kr_positive.json")

@pytest.fixture
def positive_context():
    """긍정 시나리오 AlgorithmContext"""
    return AlgorithmContext(
        symbol="005930",
        market="KR",
        news=[{"sentiment_score": 0.85, "title": "삼성전자 HBM4 양산"}],
        prices=load_fixture("price_samples/kr_5min_bars.json"),
        current_price=59000,
        position=None,
    )

@pytest.fixture
def negative_context():
    """부정 시나리오 AlgorithmContext"""
    return AlgorithmContext(
        symbol="005930",
        market="KR",
        news=[{"sentiment_score": -0.75, "title": "삼성전자 리콜 이슈"}],
        prices=load_fixture("price_samples/kr_5min_bars.json"),
        current_price=55000,
        position={"quantity": 100, "avg_cost": 58200},
    )

@pytest.fixture
def sample_ledger():
    """샘플 거래 원장 (BUY 100 + BUY 50 - SELL 30 = net 120)"""
    return [
        {"side": "BUY", "symbol": "005930", "quantity": 100, "price": 58200},
        {"side": "BUY", "symbol": "005930", "quantity": 50, "price": 57800},
        {"side": "SELL", "symbol": "005930", "quantity": 30, "price": 59500},
    ]
```

## 테스트 실행 설정

### pytest.ini

```ini
[pytest]
testpaths = tests
markers =
    unit: 단위 테스트 (외부 의존 없음)
    integration: 통합 테스트 (DB 연결 필요)
    e2e: 종단간 테스트 (전체 시스템)
    slow: 실행 시간 > 10초
asyncio_mode = auto
```

### 실행 명령

```bash
# 단위 테스트만 (CI 기본)
pytest tests/unit/ -v --cov=src --cov-report=term-missing

# 통합 테스트 포함
pytest tests/unit/ tests/integration/ -v --cov=src

# 전체 (E2E 포함)
pytest -v --cov=src --cov-report=html

# 특정 모듈만
pytest tests/unit/analysis/ -v

# 특정 마커만
pytest -m "not slow" -v
```

## 커버리지 기준

| 모듈 | 최소 커버리지 | 비고 |
|------|-------------|------|
| `risk/` | **90%** | 리스크 로직은 높은 신뢰 필수 |
| `execution/` | **85%** | 매매 실행 정확성 |
| `analysis/` | **80%** | 알고리즘 로직 |
| `collection/` | **75%** | 외부 API 의존 부분 제외 |
| `storage/` | **70%** | DB I/O 위주 |
| **전체 평균** | **80%** | Phase 2 종료 시점 목표 |

## Phase별 테스트 범위

| Phase | 필수 테스트 | 완료 기준 |
|-------|-----------|----------|
| **Phase 1** | 수집 어댑터 단위 테스트, 정규화 테스트, 저장 통합 테스트, 장전 루틴 E2E | 커버리지 70%+, 수집 파이프라인 Green |
| **Phase 2** | 알고리즘 단위 테스트 (SM/TF/MR 필수), Hybrid 융합 테스트, Paper 체결 E2E, 포지션/원장 테스트 | 커버리지 80%+, Paper Trading Green |
| **Phase 3** | 리스크 경계값 테스트 전수, Kill Switch 테스트, 브로커 어댑터 Mock 테스트, 매도 제안 E2E | 커버리지 85%+, 리스크 모듈 90%+ |

## CI/CD 연동

```yaml
# .github/workflows/test.yml (또는 Cloud Build)
name: Test
on: [push, pull_request]

jobs:
  unit-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -r requirements-dev.txt
      - run: pytest tests/unit/ -v --cov=src --cov-report=xml --cov-fail-under=80
      - uses: codecov/codecov-action@v4

  integration-test:
    runs-on: ubuntu-latest
    needs: unit-test
    services:
      redis:
        image: redis:7
        ports: ["6379:6379"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -r requirements-dev.txt
      - run: pytest tests/integration/ -v
```

## Mock 전략 요약

| 외부 의존성 | Mock 도구 | 적용 범위 |
|------------|----------|----------|
| Redis | `fakeredis` | 단위 + 통합 |
| MongoDB | `testcontainers` (통합) / `mongomock` (단위) | 전체 |
| BigQuery | `unittest.mock` + fixture JSON | 단위; 통합은 에뮬레이터 |
| Naver API | `respx` (HTTP mock) | 단위 + 통합 |
| Alpaca API | `respx` (HTTP mock) | 단위 + 통합 |
| KIS API | `respx` (HTTP mock) | 단위 + 통합 |
| LLM (Claude/Gemini) | `unittest.mock.MagicMock` | 전체 (비용 방지) |
| Telegram Bot | `respx` (HTTP mock) | 단위 |
| Cloud Scheduler | 불필요 (HTTP trigger이므로 직접 호출) | — |

## 완료 기준

- [ ] `pytest.ini` + `conftest.py` 설정 완료
- [ ] 테스트 fixture 데이터 준비 (뉴스/시세/신호 JSON)
- [ ] Phase 1 단위 테스트 작성 (수집/저장)
- [ ] Phase 1 통합 테스트 작성 (수집→저장 파이프라인)
- [ ] Phase 2 알고리즘 단위 테스트 (SM, TF, MR 필수)
- [ ] Phase 2 Hybrid 융합 테스트
- [ ] Phase 2 Paper 체결 + 원장 테스트
- [ ] Phase 3 리스크 경계값 전수 테스트
- [ ] Phase 3 Kill Switch 테스트
- [ ] Phase 3 매도 제안 E2E 테스트
- [ ] CI/CD 파이프라인 테스트 자동 실행
- [ ] 전체 커버리지 80% 이상
