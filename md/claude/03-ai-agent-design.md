# AI 트레이딩 에이전트 설계

## 1. 설계 철학

### 1.1 왜 Multi-Agent인가

단일 모놀리식 AI보다 **역할별 전문 에이전트**로 분리하는 것이 유리하다:

- **관심사 분리**: 각 에이전트가 하나의 분석 영역에 집중
- **독립적 개선**: 감성 분석 모델만 교체하거나, 기술적 분석 로직만 수정 가능
- **투명성**: 어떤 에이전트가 어떤 근거로 판단했는지 추적 가능
- **확장성**: 새로운 분석 유형(예: 옵션 그릭스 분석)을 에이전트 추가로 확장

### 1.2 참고 프레임워크

- **TradingAgents** (2025): 펀더멘탈/감성/기술 분석가, 리서처, 트레이더, 리스크 매니저로 구성된 Multi-Agent 프레임워크
- **MarketSenseAI 2.0**: 뉴스, 재무, 시장 데이터를 종합하여 투자 신호를 생성하는 모듈형 시스템

---

## 2. 에이전트 아키텍처

### 2.1 에이전트 구성

```
┌─────────────────────────────────────────────────────────────┐
│                    Orchestrator (조율자)                      │
│          전체 워크플로우 관리, 에이전트 간 통신 조율             │
└──────────┬──────────┬──────────┬──────────┬─────────────────┘
           │          │          │          │
     ┌─────▼────┐ ┌───▼────┐ ┌──▼───┐ ┌───▼──────────┐
     │ Sentiment│ │Technical│ │Funda-│ │ News         │
     │ Analyst  │ │ Analyst │ │mental│ │ Analyst      │
     │          │ │         │ │Analyst│ │              │
     └─────┬────┘ └───┬────┘ └──┬───┘ └───┬──────────┘
           │          │          │          │
           ▼          ▼          ▼          ▼
     ┌─────────────────────────────────────────────────┐
     │              Signal Aggregator (신호 종합)        │
     │     각 분석 결과를 가중 합산하여 최종 신호 생성      │
     └──────────────────────┬──────────────────────────┘
                            │
                      ┌─────▼─────┐
                      │   Risk    │
                      │  Manager  │
                      │ (최종 관문)│
                      └─────┬─────┘
                            │
                      ┌─────▼─────┐
                      │  Executor │
                      │ (주문 실행)│
                      └───────────┘
```

### 2.2 각 에이전트의 역할

| 에이전트 | 입력 | 출력 | 핵심 기능 |
|---------|------|------|-----------|
| **Sentiment Analyst** | 뉴스 기사, SNS | 감성 점수 (-1.0 ~ 1.0) | LLM 기반 감성 분석 |
| **Technical Analyst** | 시세 데이터 (OHLCV) | 기술적 시그널 | 이동평균, RSI, MACD 등 |
| **Fundamental Analyst** | 재무제표, 실적 | 밸류에이션 점수 | PER, PBR, ROE 분석 |
| **News Analyst** | 뉴스 메타데이터 | 이벤트 점수 | 뉴스 빈도/중요도 평가 |
| **Signal Aggregator** | 모든 분석 결과 | 최종 신호 (BUY/SELL/HOLD) | 가중 합산 + 충돌 해소 |
| **Risk Manager** | 최종 신호 + 포트폴리오 | 실행 허가/거부 | 리스크 한도 검증 |
| **Executor** | 실행 허가된 신호 | 주문 결과 | 증권사 API 주문 실행 |

---

## 3. 뉴스 감성 분석 엔진

### 3.1 LLM 기반 접근법

전통적인 사전(dictionary) 기반 감성 분석 대신 **LLM을 활용한 맥락 이해 기반 분석**을 사용한다.

**장점:**
- 금융 전문 용어의 맥락적 이해 ("적자 축소" → 긍정적, "실적 부진 불가피" → 부정적)
- 다국어 지원 (한국어 뉴스 + 영어 뉴스 동시 처리)
- 프롬프트 엔지니어링으로 분석 기준 즉시 조정 가능

### 3.2 감성 분석 프롬프트 설계

```python
SENTIMENT_PROMPT = """
당신은 전문 금융 애널리스트입니다. 아래 뉴스 기사를 분석하여
해당 기업의 주가에 미칠 영향을 평가하세요.

[뉴스 기사]
제목: {title}
본문: {content}
관련 종목: {ticker}

다음 JSON 형식으로 응답하세요:
{{
    "sentiment_score": <float, -1.0(매우 부정) ~ 1.0(매우 긍정)>,
    "sentiment_label": "<positive|negative|neutral>",
    "confidence": <float, 0.0 ~ 1.0>,
    "impact_timeframe": "<immediate|short_term|long_term>",
    "key_factors": ["요인1", "요인2"],
    "affected_tickers": ["종목코드1", "종목코드2"],
    "summary": "<1줄 요약>"
}}

판단 기준:
- 실적 호전, 수주 증가, 신사업 진출 → 긍정
- 실적 부진, 소송, 규제, 경영진 리스크 → 부정
- 단순 사실 보도, 업계 일반 동향 → 중립
- 확실하지 않은 경우 confidence를 낮게 설정
"""
```

### 3.3 감성 분석 파이프라인

```python
class SentimentAnalyzer:
    def __init__(self, llm_client, model="claude-sonnet-4-20250514"):
        self.llm = llm_client
        self.model = model
        self.cache = {}  # 동일 뉴스 재분석 방지

    async def analyze(self, article: NewsArticle) -> SentimentResult:
        # 1. 캐시 확인
        cache_key = hash(article.url)
        if cache_key in self.cache:
            return self.cache[cache_key]

        # 2. 프롬프트 생성
        prompt = SENTIMENT_PROMPT.format(
            title=article.title,
            content=article.content[:3000],  # 토큰 제한
            ticker=article.stock_code
        )

        # 3. LLM 호출
        response = await self.llm.create_message(
            model=self.model,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )

        # 4. 결과 파싱 및 저장
        result = self._parse_response(response)
        self.cache[cache_key] = result
        return result

    async def analyze_batch(self, articles: list[NewsArticle]) -> list[SentimentResult]:
        """여러 뉴스를 종합하여 종목별 감성 점수 산출"""
        results = await asyncio.gather(
            *[self.analyze(article) for article in articles]
        )

        # 종목별 그룹핑 및 가중 평균
        ticker_sentiments = defaultdict(list)
        for result in results:
            for ticker in result.affected_tickers:
                ticker_sentiments[ticker].append(result)

        return self._aggregate_by_ticker(ticker_sentiments)
```

### 3.4 비용 최적화

LLM API 호출 비용을 관리하기 위한 전략:

| 전략 | 설명 |
|------|------|
| **모델 계층화** | 1차 필터: Haiku (저비용), 중요 뉴스만 Sonnet으로 재분석 |
| **배치 처리** | 여러 뉴스를 묶어서 한 번에 분석 |
| **캐싱** | 동일/유사 뉴스 재분석 방지 |
| **필터링** | 관심 종목과 무관한 뉴스 사전 제외 |
| **로컬 모델 병행** | 단순 분류는 FinBERT 등 로컬 모델 사용 |

```python
class TieredSentimentAnalyzer:
    """비용 효율적인 계층적 감성 분석"""

    async def analyze(self, article):
        # 1단계: 로컬 모델로 빠른 필터링
        quick_score = self.local_model.predict(article.title)

        # 2단계: 관심 종목 관련 + 영향력 있는 뉴스만 LLM 분석
        if abs(quick_score) > 0.3 and article.stock_code in self.watchlist:
            return await self.llm_analyze(article, model="claude-haiku")

        # 3단계: 강한 시그널이면 고성능 모델로 재검증
        if abs(quick_score) > 0.7:
            return await self.llm_analyze(article, model="claude-sonnet")

        return SentimentResult(score=quick_score, confidence=0.5)
```

---

## 4. 기술적 분석 엔진

### 4.1 핵심 지표

```python
class TechnicalAnalyzer:
    """기술적 분석 지표 계산 및 시그널 생성"""

    def __init__(self):
        self.indicators = {
            "trend": [
                self.sma,           # 단순 이동평균 (20, 50, 200일)
                self.ema,           # 지수 이동평균
                self.macd,          # MACD (12, 26, 9)
            ],
            "momentum": [
                self.rsi,           # RSI (14일)
                self.stochastic,    # 스토캐스틱
            ],
            "volatility": [
                self.bollinger,     # 볼린저 밴드
                self.atr,           # ATR (Average True Range)
            ],
            "volume": [
                self.obv,           # OBV (On Balance Volume)
                self.vwap,          # VWAP
            ]
        }

    def generate_signal(self, ticker: str, ohlcv_data: pd.DataFrame) -> TechnicalSignal:
        signals = {}

        # 각 지표별 시그널 생성
        for category, indicators in self.indicators.items():
            for indicator_fn in indicators:
                signal = indicator_fn(ohlcv_data)
                signals[indicator_fn.__name__] = signal

        # 시그널 종합
        return self._aggregate_signals(signals)
```

### 4.2 시그널 판단 기준

```python
TECHNICAL_RULES = {
    "strong_buy": [
        "RSI < 30 (과매도)",
        "MACD 골든크로스",
        "볼린저 하단 터치 후 반등",
        "거래량 급증 (평균 대비 2배 이상)",
    ],
    "buy": [
        "20일선 > 50일선 (정배열)",
        "RSI 30~40 구간 상승",
        "MACD 히스토그램 양전환",
    ],
    "sell": [
        "20일선 < 50일선 (역배열)",
        "RSI 60~70 구간 하락",
        "MACD 데드크로스",
    ],
    "strong_sell": [
        "RSI > 70 (과매수)",
        "볼린저 상단 이탈 후 하락",
        "거래량 감소하며 상승 (다이버전스)",
    ]
}
```

---

## 5. 신호 종합 및 의사결정

### 5.1 가중 합산 모델

각 분석 에이전트의 결과를 가중 합산하여 최종 의사결정을 내린다.

```python
class SignalAggregator:
    # 기본 가중치 (시장 상황에 따라 동적 조정 가능)
    WEIGHTS = {
        "sentiment": 0.30,      # 뉴스 감성 분석
        "technical": 0.35,      # 기술적 분석
        "fundamental": 0.20,    # 재무 분석
        "news_frequency": 0.15, # 뉴스 빈도/중요도
    }

    def aggregate(self, signals: dict) -> TradingDecision:
        weighted_score = 0.0

        for signal_type, weight in self.WEIGHTS.items():
            if signal_type in signals:
                score = signals[signal_type].normalized_score  # -1.0 ~ 1.0
                confidence = signals[signal_type].confidence
                weighted_score += score * weight * confidence

        # 의사결정 임계값
        if weighted_score > 0.5:
            action = "STRONG_BUY"
        elif weighted_score > 0.2:
            action = "BUY"
        elif weighted_score < -0.5:
            action = "STRONG_SELL"
        elif weighted_score < -0.2:
            action = "SELL"
        else:
            action = "HOLD"

        return TradingDecision(
            action=action,
            score=weighted_score,
            confidence=self._calculate_confidence(signals),
            reasons=self._compile_reasons(signals),
        )
```

### 5.2 LLM 기반 최종 검증 (선택적)

점수 합산만으로 결정하기 어려운 복합적 상황에서 LLM을 최종 판단 보조로 활용한다.

```python
DECISION_REVIEW_PROMPT = """
아래는 {ticker} 종목에 대한 각 분석 에이전트의 결과입니다.

[감성 분석] 점수: {sentiment_score}, 근거: {sentiment_reasons}
[기술적 분석] 점수: {technical_score}, 근거: {technical_reasons}
[재무 분석] 점수: {fundamental_score}, 근거: {fundamental_reasons}
[뉴스 빈도] 최근 24시간 뉴스 {news_count}건, 평소 대비 {news_ratio}배

현재 포트폴리오 상태:
- 보유 여부: {holding_status}
- 평균 매수가: {avg_price}
- 현재가: {current_price}
- 수익률: {pnl_pct}%

시스템이 산출한 신호: {calculated_signal} (점수: {score})

이 신호가 합리적인지 검증하고, 최종 의견을 제시하세요.
특히 각 분석 간 모순이 있다면 어떤 분석을 더 신뢰해야 하는지 판단하세요.
"""
```

### 5.3 가중치 동적 조정

시장 상황에 따라 각 분석의 가중치를 조정한다:

| 시장 상황 | 감성 가중치 | 기술 가중치 | 재무 가중치 | 뉴스 빈도 |
|-----------|------------|------------|------------|-----------|
| **정상 장세** | 0.30 | 0.35 | 0.20 | 0.15 |
| **급등/급락 장** | 0.15 | 0.45 | 0.10 | 0.30 |
| **실적 시즌** | 0.20 | 0.20 | 0.45 | 0.15 |
| **이벤트 발생** | 0.40 | 0.20 | 0.10 | 0.30 |

---

## 6. 포트폴리오 관리

### 6.1 포지션 사이징

```python
class PortfolioManager:
    def calculate_position_size(self, signal: TradingDecision, ticker: str) -> int:
        """신호 강도와 리스크에 따른 매수 수량 결정"""

        total_capital = self.get_total_capital()
        current_positions = self.get_current_positions()

        # 단일 종목 최대 비중: 총 자본의 10%
        max_single_position = total_capital * 0.10

        # 신호 강도에 따른 비중 조절
        if signal.action == "STRONG_BUY":
            target_allocation = max_single_position
        elif signal.action == "BUY":
            target_allocation = max_single_position * 0.5
        else:
            return 0

        # 현재가 기준 수량 계산
        current_price = self.get_current_price(ticker)
        quantity = int(target_allocation / current_price)

        # 기존 보유분 차감
        existing = current_positions.get(ticker, 0)
        return max(0, quantity - existing)
```

### 6.2 분산 투자 규칙

```python
PORTFOLIO_RULES = {
    "max_single_stock_pct": 0.10,      # 단일 종목 최대 10%
    "max_sector_pct": 0.30,            # 단일 섹터 최대 30%
    "max_country_pct": 0.70,           # 단일 국가 최대 70%
    "min_cash_reserve_pct": 0.20,      # 최소 현금 보유 20%
    "max_total_positions": 20,         # 최대 보유 종목 수
    "kr_us_ratio": (0.5, 0.5),         # 국내:미국 목표 비율
}
```

---

## 7. 백테스팅

### 7.1 백테스팅 프레임워크

실전 투자 전 **과거 데이터로 전략을 검증**하는 것은 필수이다.

```python
class BacktestEngine:
    def __init__(self, strategy, start_date, end_date, initial_capital=100_000_000):
        self.strategy = strategy
        self.start_date = start_date
        self.end_date = end_date
        self.capital = initial_capital
        self.positions = {}
        self.trade_log = []
        self.daily_values = []

    def run(self):
        """백테스트 실행"""
        for date in self.trading_dates():
            # 1. 해당 날짜의 뉴스 + 시세 데이터 로드
            news = self.load_news(date)
            prices = self.load_prices(date)

            # 2. 전략 실행 (실시간과 동일한 로직)
            signals = self.strategy.evaluate(news, prices, self.positions)

            # 3. 시그널에 따른 매매 실행
            for signal in signals:
                self.execute_trade(signal, prices)

            # 4. 일일 포트폴리오 가치 기록
            self.daily_values.append(self.calculate_portfolio_value(prices))

    def report(self) -> BacktestReport:
        """성과 리포트 생성"""
        return BacktestReport(
            total_return=self.total_return(),
            annual_return=self.annual_return(),
            sharpe_ratio=self.sharpe_ratio(),
            max_drawdown=self.max_drawdown(),
            win_rate=self.win_rate(),
            profit_factor=self.profit_factor(),
            trade_count=len(self.trade_log),
        )
```

### 7.2 평가 지표

| 지표 | 설명 | 목표 |
|------|------|------|
| **총 수익률** | 전체 기간 수익 | 시장 수익률 초과 |
| **연환산 수익률** | 연간 환산 수익 | > 15% |
| **샤프 비율** | 위험 대비 수익 | > 1.5 |
| **최대 낙폭 (MDD)** | 고점 대비 최대 하락 | < 20% |
| **승률** | 수익 거래 비율 | > 55% |
| **손익비** | 평균 수익 / 평균 손실 | > 1.5 |

---

## 8. 단계별 구현 전략

### Phase 1: 규칙 기반 시스템
- 단순 기술적 지표 기반 매매 (이동평균 크로스, RSI)
- 뉴스 키워드 기반 필터링 (긍정/부정 키워드 사전)
- 모의투자로 검증

### Phase 2: LLM 보조 시스템
- LLM 감성 분석 도입
- 기술적 분석 + 감성 분석 종합 시그널
- 백테스팅으로 성능 검증

### Phase 3: 완전 AI 에이전트
- Multi-Agent 아키텍처 완성
- 가중치 자동 최적화
- LLM 최종 검증 레이어 추가
- 소액 실전 투자 시작

### Phase 4: 고도화
- 강화학습(RL) 기반 전략 최적화
- 대안 데이터 (SNS, 검색 트렌드) 통합
- 포트폴리오 자동 리밸런싱
