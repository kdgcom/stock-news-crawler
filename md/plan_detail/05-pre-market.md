# 05. 장전 루틴 & 일일 브리핑

> Phase 1 - Track D | 의존: Track B+C (수집+저장 완료) | 소요: Week 4~6

## 개념

매일 장 시작 전에 충분한 정보를 수집/분석하여, **장 시작 시점에 이미 그날의 전략을 갖추고 있는 상태**를 만든다.

```
장 마감 ──── 야간 ──── 장전 루틴 ──── 브리핑 ──── 장 시작
                                                    │
                           이 시점에 이미:            │
                           ✓ 전일/야간 뉴스 파악       │
                           ✓ 종목별 감성 점수 산출     │
                           ✓ 오늘의 주목 종목 선정     │
                           ✓ 기존 포지션 상태 확인     │
                           ✓ 리스크 여력 파악          │
                           ✓ 이벤트 캘린더 확인        ▼
                                                  즉시 대응 가능
```

## KR Morning Routine (07:30 KST)

### 실행 시각: 07:30 KST (장 시작 90분 전)

```
07:30 ─── 루틴 시작
  │
  ├── [1] US 마감 데이터 수집 (US 06:00 마감)
  │     ├── S&P 500, NASDAQ, DOW 종가/변동률
  │     ├── US Tier 1 종목 종가
  │     ├── US 포지션 야간 PnL
  │     └── VIX 종가
  │
  ├── [2] KR 야간/조간 뉴스 일괄 수집
  │     ├── 네이버금융: 전일 15:30 ~ 현재 (12시간)
  │     ├── DART: 전일 장후 공시
  │     └── 한경/매경 RSS: 조간 뉴스
  │
  ├── [3] 뉴스 분석
  │     ├── Tier 1 종목(30개) 관련 뉴스 전수 분석
  │     ├── 감성 점수 산출
  │     ├── 이벤트 분류 (실적, M&A, 규제 등)
  │     └── 뉴스 군집화 (중복 기사 제거)
  │
  ├── [4] 오늘의 전략 수립
  │     ├── 종목별 overnight sentiment 변화
  │     ├── US 시장 영향 평가 (상관 종목)
  │     ├── 기존 포지션 리스크 재평가
  │     └── 오늘의 watchlist 생성
  │
  └── [5] 브리핑 생성 & 발송
        └── Telegram으로 KR Morning Briefing 발송

08:30 ─── 브리핑 발송 완료, 장 시작 대기
09:00 ─── KR 장 시작, 5분 주기 운영 전환
```

### KR Morning Briefing 포맷

```
📊 KR Morning Briefing (2026-02-16 월)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

■ US 시장 마감
  S&P 500: 5,234.18 (+0.8%)
  NASDAQ:  16,421.33 (+1.2%)
  VIX:     18.3 (-0.5)

■ 야간 주요 뉴스 (KR Tier 1)
  [긍정] 삼성전자 - HBM4 양산 계획 공식 발표 (감성 +0.82)
  [부정] 현대차 - EU 관세 강화 우려 보도 (감성 -0.45)
  [중립] SK하이닉스 - 정기 주주총회 일정 공시

■ 오늘의 Watchlist (감성 변화 상위)
  1. 005930 삼성전자  ↑ 감성 +0.82 (HBM4 뉴스)
  2. 000270 기아      ↑ 거래량 3.2배 급증 (Tier 2→1 승격)
  3. 035420 NAVER     → 변동 없음

■ 기존 포지션 현황
  총 자산: ₩50,000,000 | 보유 5종목 | 현금 62%
  005930 삼성전자: +2.1% (₩58,200)
  000660 SK하이닉스: -0.8% (₩182,500)

■ 리스크 상태
  일일 손실 여력: -3.0% (사용 0%)
  주간 손실 여력: -5.0% (사용 -0.3%)
  신규 매매 가능: YES

■ 이벤트 캘린더
  - 삼성전자 4Q 실적발표 (D-3)
  - FOMC 회의록 공개 (오늘 04:00 KST 예정)
```

## US Evening Routine (22:00 KST)

### 실행 시각: 22:00 KST (US 장 시작 90분 전)

```
22:00 ─── 루틴 시작
  │
  ├── [1] KR 마감 데이터 정리
  │     ├── KOSPI, KOSDAQ 종가/변동률
  │     ├── KR 포지션 당일 PnL 확정
  │     └── KR 장 마감 후 공시
  │
  ├── [2] US 프리마켓 뉴스 수집
  │     ├── Alpaca News: KR 마감(15:30) ~ 현재
  │     ├── SEC EDGAR: 장 마감 후 Filing
  │     └── 주요 실적 발표 (애프터 마켓)
  │
  ├── [3] US 뉴스 분석
  │     ├── Tier 1 US 종목(30개) 관련 뉴스
  │     └── 감성 점수, 이벤트 분류
  │
  └── [4] US Evening Briefing 생성 & 발송

23:00 ─── 브리핑 발송 완료
23:30 ─── US 장 시작, 5분 주기 운영 전환
```

## 장전 분석 로직

### 감성 변화 감지

```python
def compute_overnight_sentiment(symbol: str, market: str):
    """전일 장중 감성 vs 야간 뉴스 감성 비교"""
    # 전일 장중 감성 (BigQuery에서 조회)
    yesterday_sentiment = query_daily_sentiment(symbol, market, days_ago=1)

    # 야간 뉴스 감성 (MongoDB에서 조회)
    overnight_news = query_recent_news(
        symbol, market,
        hours=config.collection.news.pre_market_lookback_hours  # 12시간
    )

    if not overnight_news:
        return {"change": 0, "signal": "NO_NEWS"}

    current = mean([n.sentiment_score for n in overnight_news])
    change = current - yesterday_sentiment

    return {
        "previous": yesterday_sentiment,
        "current": current,
        "change": change,
        "article_count": len(overnight_news),
        "signal": classify_change(change),  # POSITIVE / NEGATIVE / NEUTRAL
    }
```

### Watchlist 생성

```python
def generate_daily_watchlist(market: str):
    """오늘 주목할 종목 선정"""
    tier1_symbols = get_tier1_symbols(market)
    candidates = []

    for symbol in tier1_symbols:
        sentiment = compute_overnight_sentiment(symbol, market)
        volume_signal = check_premarket_volume(symbol)  # US만 해당
        event_today = check_event_calendar(symbol)

        score = (
            abs(sentiment["change"]) * 0.4 +
            volume_signal * 0.3 +
            (1.0 if event_today else 0.0) * 0.3
        )

        if score > 0.3:  # 임계값 이상만 watchlist에 추가
            candidates.append({
                "symbol": symbol,
                "score": score,
                "sentiment": sentiment,
                "event": event_today,
            })

    return sorted(candidates, key=lambda x: x["score"], reverse=True)[:10]
```

### 오늘의 전략 가중치 조정

```python
def adjust_daily_weights(market: str):
    """오늘의 시장 상황에 맞게 신호 가중치 조정"""
    # 이벤트 캘린더 확인
    earnings_count = count_earnings_today(market)
    fomc_today = is_fomc_day()
    vix_level = get_vix_close()

    if earnings_count > 5:
        return config.analysis.signal.weights.earnings_season
    elif vix_level > 25 or fomc_today:
        return config.analysis.signal.weights.volatile
    else:
        return config.analysis.signal.weights.normal
```

## Cloud Scheduler 등록

```bash
# KR 장전 루틴
gcloud scheduler jobs create http kr-pre-market \
  --schedule="30 7 * * 1-5" \
  --time-zone="Asia/Seoul" \
  --uri="https://[CLOUD_RUN_URL]/routine/kr/pre-market" \
  --http-method=POST \
  --attempt-deadline=600s

# US 장전 루틴
gcloud scheduler jobs create http us-pre-market \
  --schedule="0 22 * * 1-5" \
  --time-zone="Asia/Seoul" \
  --uri="https://[CLOUD_RUN_URL]/routine/us/pre-market" \
  --http-method=POST \
  --attempt-deadline=600s
```

## 완료 기준

- [ ] KR 장전 루틴: 07:30 실행 → 08:30 브리핑 발송 (60분 이내)
- [ ] US 장전 루틴: 22:00 실행 → 23:00 브리핑 발송 (60분 이내)
- [ ] 야간 뉴스 12시간 일괄 수집 정상
- [ ] 감성 변화 계산 정상
- [ ] Watchlist 생성 정상 (최소 1종목 이상)
- [ ] Telegram 브리핑 포맷 정상 발송
- [ ] 이벤트 캘린더 연동 (실적 발표, FOMC 등)
- [ ] LangGraph BriefingGraph 정상 실행 (체크포인트 저장 확인)
- [ ] 수집 노드 실패 시 재시도 후 부분 브리핑 생성 확인

---

## LangGraph Integration (2026-02-17)

> 장전 루틴의 다단계 파이프라인을 LangGraph StateGraph로 구현한다.
> 병렬 수집 → LLM 분석 → 브리핑 생성 → 발송의 전 과정을 하나의 그래프로 관리한다.

### 적용 사유

장전 루틴은 다음 특성으로 LangGraph에 적합하다:
1. **병렬 수집**: US 마감/KR 뉴스/DART 공시를 동시에 수집 (fan-out/fan-in)
2. **LLM 의존 단계**: 뉴스 요약, 감성 분석, 브리핑 생성에 LLM 호출 필요
3. **부분 실패 허용**: 일부 수집 실패해도 수집된 데이터만으로 브리핑 생성 가능
4. **체크포인팅**: 60분 이내 완료 요건 — 중간 실패 시 처음부터 재시작 방지

### BriefingState 정의

```python
from typing import TypedDict, Annotated
import operator

class BriefingState(TypedDict):
    """장전 브리핑 그래프의 공유 상태"""
    # --- 입력 ---
    market: str                            # "KR" | "US"
    run_date: str                          # "2026-02-17"
    run_id: str                            # UUID

    # --- 수집 결과 (병렬) ---
    us_close_data: dict | None             # US 마감 시세
    kr_news_data: list[dict] | None        # KR 야간/조간 뉴스
    dart_data: list[dict] | None           # DART 공시
    event_calendar: list[dict] | None      # 이벤트 캘린더

    # --- 분석 결과 ---
    sentiment_analysis: list[dict]         # 종목별 감성 분석
    overnight_changes: list[dict]          # 야간 감성 변화
    watchlist: list[dict]                  # 오늘의 주목 종목

    # --- 포지션 ---
    positions_summary: dict | None         # 기존 포지션 현황
    risk_status: dict | None               # 리스크 여력

    # --- 브리핑 ---
    briefing_text: str                     # 최종 브리핑 텍스트
    briefing_sent: bool                    # 발송 성공 여부

    # --- 메타 ---
    errors: Annotated[list[str], operator.add]
```

### 그래프 구조

```
                  ┌──────────────────────────────────────────────────────────┐
                  │                BriefingGraph                              │
                  │                                                          │
  START ─┬──→ [collect_us_close]      ──┐                                   │
         ├──→ [collect_kr_news]        ──┼──→ [analyze_sentiment]            │
         ├──→ [collect_dart]           ──┘         │                         │
         └──→ [collect_events]     ──────────→     │                         │
                  (4종 병렬)                        ▼                         │
                                          [build_watchlist]                  │
                                                   │                         │
                                       ┌───────────┤                         │
                                       ▼           ▼                         │
                              [fetch_positions] [adjust_weights]             │
                                       │           │                         │
                                       └─────┬─────┘                        │
                                             ▼                               │
                                    [generate_briefing]  ← LLM 요약          │
                                             │                               │
                                             ▼                               │
                                    [send_telegram]                          │
                                             │                               │
                                           END                               │
                  └──────────────────────────────────────────────────────────┘
```

### 핵심 노드 구현

#### 수집 노드 (병렬 fan-out)

```python
def collect_us_close(state: BriefingState) -> dict:
    """US 마감 시세 수집 — S&P500, NASDAQ, DOW, VIX, Tier1 US 종가"""
    try:
        data = us_market_collector.fetch_close_data()
        return {"us_close_data": data}
    except Exception as e:
        return {"us_close_data": None, "errors": [f"US_CLOSE_FAIL: {e}"]}

def collect_kr_news(state: BriefingState) -> dict:
    """KR 야간/조간 뉴스 일괄 수집 (12시간)"""
    try:
        lookback = config.collection.news.pre_market_lookback_hours
        articles = kr_news_collector.fetch_since(hours=lookback)
        return {"kr_news_data": articles}
    except Exception as e:
        return {"kr_news_data": None, "errors": [f"KR_NEWS_FAIL: {e}"]}

def collect_dart(state: BriefingState) -> dict:
    """DART 장후 공시 수집"""
    try:
        filings = dart_collector.fetch_after_market()
        return {"dart_data": filings}
    except Exception as e:
        return {"dart_data": None, "errors": [f"DART_FAIL: {e}"]}

def collect_events(state: BriefingState) -> dict:
    """오늘의 이벤트 캘린더 (실적 발표, FOMC 등)"""
    try:
        events = event_calendar.fetch_today(state["market"])
        return {"event_calendar": events}
    except Exception as e:
        return {"event_calendar": None, "errors": [f"EVENTS_FAIL: {e}"]}
```

#### 분석 노드 (LLM 호출)

```python
def analyze_sentiment(state: BriefingState) -> dict:
    """Tier 1 종목별 뉴스 감성 분석 + 야간 변화 계산"""
    news = state.get("kr_news_data") or []
    dart = state.get("dart_data") or []
    all_items = news + dart

    if not all_items:
        return {
            "sentiment_analysis": [],
            "overnight_changes": [],
            "errors": ["NO_NEWS_DATA_FOR_ANALYSIS"],
        }

    tier1 = get_tier1_symbols(state["market"])
    sentiments = []
    changes = []

    for symbol in tier1:
        related = [a for a in all_items if symbol in a.get("symbols", [])]
        if not related:
            continue

        # LLM 감성 분석 (배치)
        sentiment = analyze_news_sentiment_batch(related, symbol)
        sentiments.append({"symbol": symbol, **sentiment})

        # 야간 변화 계산
        change = compute_overnight_sentiment(symbol, state["market"])
        changes.append({"symbol": symbol, **change})

    return {
        "sentiment_analysis": sentiments,
        "overnight_changes": changes,
    }

def build_watchlist(state: BriefingState) -> dict:
    """감성 변화 + 이벤트 기반 오늘의 Watchlist 생성"""
    watchlist = generate_daily_watchlist_from_state(
        changes=state["overnight_changes"],
        events=state.get("event_calendar") or [],
        market=state["market"],
    )
    return {"watchlist": watchlist}
```

#### 브리핑 생성 노드 (LLM 요약)

```python
from langchain_core.prompts import ChatPromptTemplate

def generate_briefing(state: BriefingState) -> dict:
    """전체 분석 결과를 LLM으로 한글 브리핑 생성"""
    prompt = ChatPromptTemplate.from_messages([
        ("system", BRIEFING_SYSTEM_PROMPT),
        ("human", """
시장: {market} | 날짜: {run_date}

■ US 마감:
{us_close_summary}

■ 주요 뉴스 ({news_count}건):
{news_summary}

■ 감성 변화 상위:
{sentiment_changes}

■ Watchlist:
{watchlist}

■ 포지션 현황:
{positions}

■ 리스크 상태:
{risk_status}

■ 이벤트:
{events}

위 정보를 기반으로 Morning Briefing을 생성하세요.
정해진 포맷을 준수하세요.
"""),
    ])

    chain = prompt | llm_fast
    briefing = chain.invoke(build_briefing_context(state))

    return {"briefing_text": briefing.content}


def send_telegram(state: BriefingState) -> dict:
    """생성된 브리핑을 Telegram으로 발송"""
    try:
        notifier = TelegramNotifier(config)
        notifier.send(state["briefing_text"], parse_mode="HTML")
        return {"briefing_sent": True}
    except Exception as e:
        return {"briefing_sent": False, "errors": [f"TELEGRAM_FAIL: {e}"]}
```

### 그래프 빌드

```python
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver

def build_briefing_graph() -> StateGraph:
    graph = StateGraph(BriefingState)

    # 수집 노드 (병렬)
    graph.add_node("collect_us_close", collect_us_close)
    graph.add_node("collect_kr_news",  collect_kr_news)
    graph.add_node("collect_dart",     collect_dart)
    graph.add_node("collect_events",   collect_events)

    # 분석 노드
    graph.add_node("analyze_sentiment", analyze_sentiment)
    graph.add_node("build_watchlist",   build_watchlist)
    graph.add_node("fetch_positions",   fetch_positions)
    graph.add_node("adjust_weights",    adjust_daily_weights_node)

    # 출력 노드
    graph.add_node("generate_briefing", generate_briefing)
    graph.add_node("send_telegram",     send_telegram)

    # 엣지: START → 수집 4종 병렬
    for node in ["collect_us_close", "collect_kr_news", "collect_dart", "collect_events"]:
        graph.add_edge(START, node)

    # 수집 → 분석 (fan-in)
    for node in ["collect_us_close", "collect_kr_news", "collect_dart", "collect_events"]:
        graph.add_edge(node, "analyze_sentiment")

    graph.add_edge("analyze_sentiment", "build_watchlist")
    graph.add_edge("build_watchlist", "fetch_positions")
    graph.add_edge("build_watchlist", "adjust_weights")
    graph.add_edge("fetch_positions", "generate_briefing")
    graph.add_edge("adjust_weights", "generate_briefing")
    graph.add_edge("generate_briefing", "send_telegram")
    graph.add_edge("send_telegram", END)

    checkpointer = SqliteSaver.from_conn_string("data/langgraph_checkpoints.db")
    return graph.compile(checkpointer=checkpointer)


# Cloud Run 엔드포인트에서 호출
briefing_graph = build_briefing_graph()

result = briefing_graph.invoke(
    {
        "market": "KR",
        "run_date": "2026-02-17",
        "run_id": str(uuid4()),
        "errors": [],
    },
    config={"configurable": {"thread_id": f"briefing-KR-2026-02-17"}},
)
```

### 부분 실패 처리

```python
# 각 수집 노드는 실패 시 None + errors 반환
# 분석 노드는 None 데이터를 건너뜀
# 브리핑 생성 노드는 수집된 데이터만으로 브리핑 구성

# 예: DART 실패, 나머지 성공 시
#   → "■ DART 공시: 수집 실패 (수동 확인 필요)" 포함하여 브리핑 생성
#   → errors 리스트에 "DART_FAIL" 기록 → 모니터링 메트릭 반영
```
