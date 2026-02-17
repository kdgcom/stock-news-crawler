# 06. 분석 엔진 — 플러그인 알고리즘 아키텍처

> Phase 2 - Track A | 의존: Phase 1 완료 | 소요: Week 5~10

## 설계 원칙

1. **모든 알고리즘은 동일한 인터페이스**를 구현한다 → 교체/추가가 자유로움
2. **settings.yaml에서 활성 알고리즘을 선택**한다 → 코드 변경 없이 전략 교체
3. **앙상블 모드**로 여러 알고리즘을 동시 실행하고 합의할 수 있다
4. **Champion/Challenger** 비교 모드로 신규 알고리즘을 안전하게 검증한다

## 아키텍처

```
settings.yaml
  algorithms.active: "ensemble"
         │
         ▼
┌──────────────────────────────────────────────────────────────────┐
│  AlgorithmRouter                                                 │
│                                                                  │
│  active="ensemble" → EnsembleRunner                              │
│  active="technical_trend" → 단일 알고리즘 직접 실행                 │
│                                                                  │
│  comparison.enabled=true → Champion 실거래 + Challenger shadow     │
└──────────┬───────────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────────────┐
│  EnsembleRunner (mode: weighted_vote)                            │
│                                                                  │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐        │
│  │  SM  │ │  TF  │ │  MR  │ │  EC  │ │  VP  │ │  OG  │        │
│  │ 0.20 │ │ 0.25 │ │ 0.15 │ │ 0.20 │ │ 0.10 │ │ 0.10 │        │
│  └──┬───┘ └──┬───┘ └──┬───┘ └──┬───┘ └──┬───┘ └──┬───┘        │
│     │ BUY    │ BUY    │ HOLD   │ BUY    │ HOLD   │ SELL        │
│     │ 0.72   │ 0.65   │ 0.10   │ 0.80   │ -0.05  │ -0.40       │
│     └────────┴────────┴────────┴────────┴────────┴──────┐      │
│                         │ 가중 합산                       │      │
│                         ▼                                │      │
│              Score = 0.20×0.72 + 0.25×0.65 + 0.15×0.10  │      │
│                    + 0.20×0.80 + 0.10×(-0.05)            │      │
│                    + 0.10×(-0.40) = 0.431                │      │
│                         │                                │      │
│              > min_agreement(0.5)? → 아니오 → HOLD       │      │
└──────────────────────────────────────────────────────────────────┘
```

## 공통 인터페이스

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

@dataclass
class Signal:
    symbol: str
    market: str
    decision: Literal["BUY", "SELL", "HOLD"]
    score: float               # -1.0 ~ +1.0
    confidence: float          # 0.0 ~ 1.0
    algorithm: str             # 알고리즘 식별자
    reason_codes: list[str]
    details: dict              # 알고리즘별 상세 정보

@dataclass
class AlgorithmContext:
    """알고리즘에 전달되는 공통 컨텍스트"""
    symbol: str
    market: str
    price_bars: list[dict]     # 최근 N개 5분봉 (Redis 캐시)
    daily_bars: list[dict]     # 최근 N일 일봉 (BigQuery)
    news_events: list[dict]    # 최근 뉴스 (MongoDB enriched)
    sentiment_current: float   # 현재 감성 점수
    sentiment_previous: float  # 이전 주기 감성 점수
    position: dict | None      # 현재 보유 포지션 (Redis)
    portfolio: dict            # 포트폴리오 상태
    regime: str                # 시장 체제 (trending_up|down|sideways|volatile)

class BaseAlgorithm(ABC):
    def __init__(self, config: dict):
        self.config = config

    @abstractmethod
    def generate_signal(self, ctx: AlgorithmContext) -> Signal:
        """매수/매도/관망 신호 생성"""
        ...

    @abstractmethod
    def required_data(self) -> list[str]:
        """필요한 데이터 종류 선언"""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        ...
```

## 알고리즘 라우터

```python
class AlgorithmRouter:
    def __init__(self, config):
        self.config = config
        self.algorithms = self._load_algorithms()

    def _load_algorithms(self) -> dict[str, BaseAlgorithm]:
        """enabled=true인 알고리즘만 로드"""
        registry = {
            "sentiment_momentum": SentimentMomentum,
            "technical_trend": TechnicalTrend,
            "mean_reversion": MeanReversion,
            "event_catalyst": EventCatalyst,
            "volume_price": VolumePriceDivergence,
            "overnight_gap": OvernightGap,
            "sector_correlation": SectorCorrelation,
            "regime_adaptive": RegimeAdaptive,
        }
        loaded = {}
        for name, cls in registry.items():
            algo_config = self.config.algorithms.get(name, {})
            if algo_config.get("enabled", False):
                loaded[name] = cls(algo_config)
        return loaded

    def run(self, ctx: AlgorithmContext) -> Signal:
        active = self.config.algorithms.active

        if active == "ensemble":
            return self._run_ensemble(ctx)
        elif active in self.algorithms:
            return self.algorithms[active].generate_signal(ctx)
        else:
            raise ValueError(f"Unknown algorithm: {active}")

    def _run_ensemble(self, ctx: AlgorithmContext) -> Signal:
        ensemble_cfg = self.config.algorithms.ensemble
        results = []

        for member in ensemble_cfg.members:
            algo_name = member["algorithm"]
            weight = member["weight"]
            if algo_name in self.algorithms:
                signal = self.algorithms[algo_name].generate_signal(ctx)
                results.append((signal, weight))

        return self._aggregate(results, ensemble_cfg)

    def _aggregate(self, results, cfg) -> Signal:
        if cfg.mode == "weighted_vote":
            return self._weighted_vote(results, cfg)
        elif cfg.mode == "majority_vote":
            return self._majority_vote(results, cfg)
        elif cfg.mode == "best_confidence":
            return self._best_confidence(results)

    def _weighted_vote(self, results, cfg) -> Signal:
        weighted_score = sum(s.score * w for s, w in results)
        total_weight = sum(w for _, w in results)
        normalized = weighted_score / total_weight if total_weight > 0 else 0

        if abs(normalized) < cfg.min_agreement:
            decision = "HOLD"
        elif normalized > 0:
            decision = "BUY"
        else:
            decision = "SELL"

        return Signal(
            decision=decision,
            score=normalized,
            confidence=abs(normalized),
            algorithm="ensemble",
            reason_codes=[f"{s.algorithm}:{s.decision}" for s, _ in results],
            details={"member_signals": [(s.algorithm, s.score, w) for s, w in results]},
            # ...
        )
```

---

## 알고리즘 1: Sentiment Momentum (SM) — 감성 변화 추세

### 핵심 아이디어

뉴스 감성의 **변화 방향과 속도**를 추적한다. 감성이 상승 추세면 매수, 하락 추세면 매도.
단순 감성 점수가 아니라 **모멘텀**(변화율)에 주목.

### 적합한 시장 상황

- 이벤트 드리븐 (실적 발표, M&A, 정책 변경)
- 뉴스 빈도가 높은 종목

### 로직

```python
class SentimentMomentum(BaseAlgorithm):
    name = "sentiment_momentum"

    def required_data(self) -> list[str]:
        return ["news_events", "sentiment_current", "sentiment_previous"]

    def generate_signal(self, ctx: AlgorithmContext) -> Signal:
        cfg = self.config
        news = ctx.news_events

        # 최소 기사 수 미달 → 신뢰도 부족
        if len(news) < cfg["min_articles"]:
            return Signal(decision="HOLD", score=0, confidence=0.2,
                          reason_codes=["INSUFFICIENT_NEWS"], ...)

        # 시간 가중 감성 점수 (최신 뉴스에 높은 가중치)
        weighted_score = 0
        total_weight = 0
        for article in news:
            hours_ago = (now() - article["analyzed_at_utc"]).total_seconds() / 3600
            time_weight = cfg["decay_factor"] ** hours_ago
            article_score = (
                article["sentiment_score"] * cfg["weight_sentiment"] +
                article["novelty_score"] * cfg["weight_novelty"] +
                article["reliability_score"] * cfg["weight_reliability"]
            )
            weighted_score += article_score * time_weight
            total_weight += time_weight

        current = weighted_score / total_weight if total_weight > 0 else 0

        # 감성 모멘텀 = 현재 - 이전 주기
        momentum = current - ctx.sentiment_previous

        # 신호 결정
        if abs(momentum) < cfg["change_threshold"]:
            return Signal(decision="HOLD", score=momentum, ...)

        if momentum > 0:
            return Signal(decision="BUY", score=min(momentum, 1.0),
                          confidence=min(abs(momentum) * 2, 1.0),
                          reason_codes=["SENTIMENT_MOMENTUM_UP"], ...)
        else:
            return Signal(decision="SELL", score=max(momentum, -1.0),
                          confidence=min(abs(momentum) * 2, 1.0),
                          reason_codes=["SENTIMENT_MOMENTUM_DOWN"], ...)
```

---

## 알고리즘 2: Technical Trend (TF) — 기술적 추세 추종

### 핵심 아이디어

추세가 확인되면 따라가고, 추세가 꺾이면 빠져나온다. **다중 확인**(SMA 크로스 + MACD + 거래량)으로 거짓 신호를 필터링.

### 적합한 시장 상황

- 명확한 상승/하락 추세
- 거래량이 충분한 대형주

### 로직

```python
class TechnicalTrend(BaseAlgorithm):
    name = "technical_trend"

    def required_data(self) -> list[str]:
        return ["price_bars"]

    def generate_signal(self, ctx: AlgorithmContext) -> Signal:
        bars = ctx.price_bars
        closes = [b["close"] for b in bars]
        volumes = [b["volume"] for b in bars]
        cfg = self.config

        # SMA 크로스
        sma_short = sma(closes, 20)
        sma_long = sma(closes, 50)
        sma_cross = "golden" if sma_short > sma_long else "dead"
        sma_prev = "golden" if sma(closes[:-1], 20) > sma(closes[:-1], 50) else "dead"
        sma_just_crossed = sma_cross != sma_prev

        # MACD 확인
        macd_line, signal_line, histogram = compute_macd(closes, 12, 26, 9)
        macd_bullish = histogram[-1] > 0 and histogram[-1] > histogram[-2]

        # 거래량 확인
        vol_avg = mean(volumes[-20:])
        vol_confirm = volumes[-1] > vol_avg * 1.5

        # AND 조건: 모두 충족 시 진입
        entry_checks = []
        if cfg["entry_conditions"]["sma_cross"]:
            entry_checks.append(sma_just_crossed)
        if cfg["entry_conditions"]["macd_confirm"]:
            entry_checks.append(macd_bullish if sma_cross == "golden" else not macd_bullish)
        if cfg["entry_conditions"]["volume_confirm"]:
            entry_checks.append(vol_confirm)

        all_confirmed = all(entry_checks)

        if all_confirmed and sma_cross == "golden":
            # ATR 기반 손절가 계산
            atr = compute_atr(bars, 14)
            stop_distance = atr * cfg["atr_stop_multiplier"]
            return Signal(
                decision="BUY", score=0.7,
                confidence=0.8 if vol_confirm else 0.6,
                reason_codes=["SMA_GOLDEN_CROSS", "MACD_CONFIRM", "VOLUME_CONFIRM"],
                details={"stop_loss_distance": stop_distance, "atr": atr},
            )
        elif all_confirmed and sma_cross == "dead":
            return Signal(decision="SELL", score=-0.7, ...)

        # 기존 포지션 청산 조건
        if ctx.position and cfg["exit_conditions"]["sma_reverse"]:
            if sma_cross == "dead" and ctx.position["side"] == "long":
                return Signal(decision="SELL", score=-0.5,
                              reason_codes=["SMA_REVERSE_EXIT"], ...)

        return Signal(decision="HOLD", score=0, ...)
```

---

## 알고리즘 3: Mean Reversion (MR) — 평균 회귀

### 핵심 아이디어

가격이 극단으로 이동하면 평균으로 돌아오는 성질을 이용. **과매도에서 사고, 과매수에서 판다.**
거래량 다이버전스를 확인하여 진짜 바닥/천장을 구별.

### 적합한 시장 상황

- 횡보/박스권 장세
- 변동성이 안정적인 구간

### 로직

```python
class MeanReversion(BaseAlgorithm):
    name = "mean_reversion"

    def generate_signal(self, ctx: AlgorithmContext) -> Signal:
        bars = ctx.price_bars
        closes = [b["close"] for b in bars]
        volumes = [b["volume"] for b in bars]
        cfg = self.config

        rsi = compute_rsi(closes, 14)
        bb_upper, bb_middle, bb_lower = compute_bollinger(closes, 20, 2.0)
        current_price = closes[-1]

        # 매수: RSI 과매도 + 볼린저 하단 접근 + 거래량 다이버전스
        is_oversold = rsi < cfg["rsi_oversold"]
        near_lower_band = current_price <= bb_lower * (1 + cfg["bollinger_entry"] * 0.01)
        vol_divergence = (
            closes[-1] < closes[-3] and  # 가격 하락
            volumes[-1] < volumes[-3]     # 거래량도 감소 → 매도 압력 소진
        ) if cfg["require_volume_divergence"] else True

        if is_oversold and near_lower_band and vol_divergence:
            return Signal(
                decision="BUY", score=0.6,
                confidence=0.7,
                reason_codes=["RSI_OVERSOLD", "BOLLINGER_LOWER", "VOLUME_DIVERGENCE"],
                details={"rsi": rsi, "bb_lower": bb_lower, "target": bb_middle},
            )

        # 매도: RSI 과매수 + 볼린저 상단 접근
        is_overbought = rsi > cfg["rsi_overbought"]
        near_upper_band = current_price >= bb_upper * (1 - cfg["bollinger_entry"] * 0.01)

        if is_overbought and near_upper_band:
            return Signal(decision="SELL", score=-0.6, ...)

        # 청산: 중심선 복귀
        if ctx.position:
            if abs(current_price - bb_middle) / bb_middle < 0.005:
                return Signal(decision="SELL", score=-0.3,
                              reason_codes=["MEAN_REVERSION_TARGET"], ...)

        return Signal(decision="HOLD", score=0, ...)
```

---

## 알고리즘 4: Event Catalyst (EC) — 이벤트 촉매

### 핵심 아이디어

**특정 이벤트 유형은 예측 가능한 가격 반응**을 유발한다. 이벤트를 분류하고 기대 방향으로 포지션을 잡되, 반응 윈도우 내에서만 유효.

### 적합한 시장 상황

- 실적 발표 시즌
- M&A, 규제, 제품 출시 등 명확한 이벤트

### 로직

```python
class EventCatalyst(BaseAlgorithm):
    name = "event_catalyst"

    def generate_signal(self, ctx: AlgorithmContext) -> Signal:
        cfg = self.config
        recent_events = [
            e for e in ctx.news_events
            if (now() - e["analyzed_at_utc"]).total_seconds() / 60
               < cfg["reaction_window_minutes"]
            and e["confidence"] >= cfg["min_event_confidence"]
        ]

        if not recent_events:
            return Signal(decision="HOLD", score=0,
                          reason_codes=["NO_RECENT_EVENT"], ...)

        # 이벤트 점수 합산 (가장 강한 이벤트 우선)
        event_scores = []
        for event in recent_events:
            event_type = event["event_type"]
            base_weight = cfg["event_weights"].get(event_type, 0)
            if base_weight == 0:
                continue

            # 시간 감쇠
            minutes_ago = (now() - event["analyzed_at_utc"]).total_seconds() / 60
            fade_hours = cfg["fade_after_hours"]
            time_factor = max(0, 1 - minutes_ago / (fade_hours * 60))

            event_scores.append({
                "type": event_type,
                "score": base_weight * time_factor * event["confidence"],
                "event_id": event["event_id"],
            })

        if not event_scores:
            return Signal(decision="HOLD", score=0, ...)

        total_score = sum(e["score"] for e in event_scores)
        strongest = max(event_scores, key=lambda e: abs(e["score"]))

        if total_score > 0.3:
            return Signal(decision="BUY", score=min(total_score, 1.0),
                          reason_codes=[f"EVENT_{strongest['type'].upper()}"],
                          details={"events": event_scores}, ...)
        elif total_score < -0.3:
            return Signal(decision="SELL", score=max(total_score, -1.0), ...)

        return Signal(decision="HOLD", score=total_score, ...)
```

---

## 알고리즘 5: Volume-Price Divergence (VP) — 거래량-가격 괴리

### 핵심 아이디어

**거래량은 가격에 선행한다.** 가격은 움직이지 않는데 거래량이 급증하면 세력이 매집/분배하는 것. OBV 다이버전스와 결합하여 전환점을 포착.

### 적합한 시장 상황

- 횡보 후 돌파 직전
- 대형주의 조용한 매집 구간

### 로직

```python
class VolumePriceDivergence(BaseAlgorithm):
    name = "volume_price"

    def generate_signal(self, ctx: AlgorithmContext) -> Signal:
        bars = ctx.price_bars
        cfg = self.config

        # --- 매집 감지 (Accumulation) ---
        recent = bars[-cfg["accumulation"]["consecutive_bars"]:]
        price_changes = [abs(b["close"] - b["open"]) / b["open"] for b in recent]
        avg_price_change = mean(price_changes)
        vol_avg_20 = mean([b["volume"] for b in bars[-20:]])
        vol_recent = mean([b["volume"] for b in recent])

        is_accumulation = (
            avg_price_change < cfg["accumulation"]["price_change_max_pct"] and
            vol_recent > vol_avg_20 * cfg["accumulation"]["volume_surge_ratio"]
        )

        if is_accumulation:
            return Signal(decision="BUY", score=0.5,
                          confidence=0.65,
                          reason_codes=["ACCUMULATION_DETECTED"], ...)

        # --- 분배 감지 (Distribution) ---
        price_up = bars[-1]["close"] > bars[-5]["close"]
        vol_decline = (
            mean([b["volume"] for b in bars[-3:]]) <
            mean([b["volume"] for b in bars[-8:-3]]) * cfg["distribution"]["volume_decline_ratio"]
        )

        if price_up and vol_decline:
            return Signal(decision="SELL", score=-0.5,
                          reason_codes=["DISTRIBUTION_DETECTED"], ...)

        # --- OBV 다이버전스 ---
        obv = compute_obv(bars[-cfg["obv_divergence_bars"]:])
        price_trend = bars[-1]["close"] - bars[-cfg["obv_divergence_bars"]]["close"]
        obv_trend = obv[-1] - obv[0]

        if price_trend < 0 and obv_trend > 0:  # 가격↓ + OBV↑ = 강세 다이버전스
            return Signal(decision="BUY", score=0.4,
                          reason_codes=["OBV_BULLISH_DIVERGENCE"], ...)
        elif price_trend > 0 and obv_trend < 0:  # 가격↑ + OBV↓ = 약세 다이버전스
            return Signal(decision="SELL", score=-0.4,
                          reason_codes=["OBV_BEARISH_DIVERGENCE"], ...)

        return Signal(decision="HOLD", score=0, ...)
```

---

## 알고리즘 6: Overnight Gap (OG) — 장전 갭 전략

### 핵심 아이디어

장 시작 시 갭이 발생하면 두 가지 전략 중 선택:
- **갭 메움 (Gap Fill)**: 갭의 반대 방향 → 갭이 메워질 것으로 예상
- **갭 추종 (Gap & Go)**: 갭 방향으로 → 뉴스 모멘텀이 지속될 것으로 예상

`sentiment_confirm` 설정으로 뉴스 감성과 일치할 때만 추종.

### 적합한 시장 상황

- 장전 루틴(05-pre-market.md)에서 감지된 갭
- 장 시작 직후 10~120분

### 로직

```python
class OvernightGap(BaseAlgorithm):
    name = "overnight_gap"

    def generate_signal(self, ctx: AlgorithmContext) -> Signal:
        cfg = self.config
        bars = ctx.price_bars

        # 장 시작 후 경과 봉 수 (5분 기준)
        bars_since_open = get_bars_since_market_open(ctx.market)
        if bars_since_open < cfg["entry_delay_bars"]:
            return Signal(decision="HOLD", reason_codes=["GAP_DELAY_PERIOD"], ...)
        if bars_since_open > cfg["max_hold_bars"]:
            return Signal(decision="HOLD", reason_codes=["GAP_WINDOW_EXPIRED"], ...)

        # 갭 크기 계산
        prev_close = get_previous_close(ctx.symbol, ctx.market)
        open_price = get_today_open(ctx.symbol, ctx.market)
        gap_pct = (open_price - prev_close) / prev_close

        if abs(gap_pct) < cfg["min_gap_pct"]:
            return Signal(decision="HOLD", reason_codes=["GAP_TOO_SMALL"], ...)

        gap_direction = "up" if gap_pct > 0 else "down"

        # 감성 확인
        sentiment_aligned = False
        if cfg["sentiment_confirm"]:
            if gap_direction == "up" and ctx.sentiment_current > 0.3:
                sentiment_aligned = True
            elif gap_direction == "down" and ctx.sentiment_current < -0.3:
                sentiment_aligned = True
        else:
            sentiment_aligned = True  # 확인 비활성화 시 항상 통과

        if cfg["gap_fill_mode"]:
            # 갭 메움: 갭의 반대 방향 (감성 불일치 시 유리)
            if gap_direction == "up" and not sentiment_aligned:
                return Signal(decision="SELL", score=-0.5,
                              reason_codes=["GAP_FILL_SHORT"], ...)
            elif gap_direction == "down" and not sentiment_aligned:
                return Signal(decision="BUY", score=0.5,
                              reason_codes=["GAP_FILL_LONG"], ...)
        else:
            # 갭 추종: 갭 방향 (감성 일치 시 유리)
            if gap_direction == "up" and sentiment_aligned:
                return Signal(decision="BUY", score=0.6,
                              reason_codes=["GAP_AND_GO_LONG"], ...)
            elif gap_direction == "down" and sentiment_aligned:
                return Signal(decision="SELL", score=-0.6,
                              reason_codes=["GAP_AND_GO_SHORT"], ...)

        return Signal(decision="HOLD", score=0, ...)
```

---

## 알고리즘 7: Sector Correlation (SC) — 섹터 연동

### 핵심 아이디어

같은 섹터 내 **리더 종목이 먼저 움직이면, 래거 종목이 따라온다.** 반도체 섹터에서 삼성전자가 급등하면 SK하이닉스가 후행하는 패턴.

### 적합한 시장 상황

- 섹터 단위 뉴스 (반도체 호황, 자동차 관세 등)
- 섹터 로테이션 구간

### 로직

```python
class SectorCorrelation(BaseAlgorithm):
    name = "sector_correlation"

    def generate_signal(self, ctx: AlgorithmContext) -> Signal:
        cfg = self.config
        symbol = ctx.symbol
        sector = get_sector(symbol)
        sector_peers = get_sector_symbols(sector, ctx.market)

        # 섹터 리더 종목 모멘텀 (최근 N봉)
        leader_momentum = {}
        for peer in sector_peers:
            if peer == symbol:
                continue
            peer_bars = get_price_bars(peer, count=cfg["sector_momentum_window"])
            if peer_bars:
                ret = (peer_bars[-1]["close"] - peer_bars[0]["close"]) / peer_bars[0]["close"]
                leader_momentum[peer] = ret

        if not leader_momentum:
            return Signal(decision="HOLD", ...)

        # 리더: 가장 큰 움직임을 보인 종목
        leader = max(leader_momentum, key=lambda k: abs(leader_momentum[k]))
        leader_return = leader_momentum[leader]

        # 상관계수 확인
        corr = compute_correlation(symbol, leader, days=60)
        if abs(corr) < cfg["min_correlation"]:
            return Signal(decision="HOLD", reason_codes=["LOW_CORRELATION"], ...)

        # 현재 종목의 반응 래그 확인
        my_bars = ctx.price_bars[-cfg["leader_lag_bars"]:]
        my_return = (my_bars[-1]["close"] - my_bars[0]["close"]) / my_bars[0]["close"]

        # 리더는 움직였지만 래거는 아직 → 기회
        lag_gap = leader_return - my_return
        if abs(lag_gap) > 0.01:  # 1% 이상 괴리
            if lag_gap > 0:
                return Signal(decision="BUY", score=min(lag_gap * 10, 0.7),
                              reason_codes=["SECTOR_LAG_BUY"],
                              details={"leader": leader, "gap": lag_gap}, ...)
            else:
                return Signal(decision="SELL", score=max(lag_gap * 10, -0.7), ...)

        return Signal(decision="HOLD", score=0, ...)
```

---

## 알고리즘 8: Regime-Adaptive (RA) — 시장 체제 적응형

### 핵심 아이디어

**시장 체제를 먼저 판별하고, 해당 체제에 최적인 알고리즘을 선택**한다. 상승 추세에서는 추세 추종, 횡보에서는 평균 회귀, 변동성 장에서는 이벤트 기반.

### 체제 판별

```python
class RegimeAdaptive(BaseAlgorithm):
    name = "regime_adaptive"

    def _detect_regime(self, daily_bars: list[dict]) -> str:
        closes = [b["close"] for b in daily_bars]
        cfg = self.config["regime_detection"]

        # 추세 판정: SMA 50 기울기
        sma_50 = sma(closes, cfg["trend_window"])
        sma_20 = sma(closes, cfg["volatility_window"])
        trend_slope = (sma_50 - sma(closes[:-5], cfg["trend_window"])) / sma_50

        # 변동성 판정: 최근 20일 표준편차
        vol_current = stdev(closes[-cfg["volatility_window"]:])
        vol_long = stdev(closes[-cfg["trend_window"]:])
        vol_ratio = vol_current / vol_long if vol_long > 0 else 1

        if vol_ratio > 1.5:
            return "volatile"
        elif vol_ratio < 0.6:
            return "low_volatility"
        elif trend_slope > 0.002:
            return "trending_up"
        elif trend_slope < -0.002:
            return "trending_down"
        else:
            return "sideways"

    def generate_signal(self, ctx: AlgorithmContext) -> Signal:
        regime = self._detect_regime(ctx.daily_bars)
        cfg = self.config

        # 체제별 최적 알고리즘 선택
        algo_name = cfg["regime_algorithm_map"].get(regime, "sentiment_momentum")
        delegate = AlgorithmRouter.algorithms.get(algo_name)

        if delegate is None:
            return Signal(decision="HOLD", reason_codes=["DELEGATE_NOT_FOUND"], ...)

        signal = delegate.generate_signal(ctx)
        # 원본 알고리즘 정보에 체제 정보 추가
        signal.details["regime"] = regime
        signal.details["delegate_algorithm"] = algo_name
        signal.reason_codes.insert(0, f"REGIME_{regime.upper()}")
        return signal
```

### 체제-알고리즘 매핑

| 체제 | 특징 | 최적 알고리즘 | 사유 |
|------|------|-------------|------|
| `trending_up` | 상승 추세 | Technical Trend (TF) | 추세 추종이 유리 |
| `trending_down` | 하락 추세 | Technical Trend (TF) | 숏 또는 청산 |
| `sideways` | 횡보/박스 | Mean Reversion (MR) | 밴드 반등이 유리 |
| `volatile` | 고변동성 | Event Catalyst (EC) | 이벤트 반응만 신뢰 |
| `low_volatility` | 저변동성 | Sentiment Momentum (SM) | 뉴스 변화가 유일한 동력 |

---

## 앙상블 합산 모드

`settings.yaml`의 `algorithms.ensemble.mode`로 선택:

| 모드 | 설명 | 적합한 상황 |
|------|------|-----------|
| `weighted_vote` | 가중 점수 합산 | 기본값. 다수 의견 반영 |
| `majority_vote` | 다수결 (BUY 수 vs SELL 수) | 보수적. 방향 합의 |
| `best_confidence` | 신뢰도 최고 알고리즘 1개만 채택 | 강한 신호만 실행 |
| `stack` | Phase 3용. ML 모델이 알고리즘 출력을 피처로 사용 | 고도화 단계 |

## Champion / Challenger 비교

```yaml
algorithms:
  comparison:
    enabled: true
    champion: "ensemble"            # 실제 매매에 사용
    challenger: "regime_adaptive"   # Paper Only (shadow)
    switch_after_days: 30
    switch_metric: "sharpe"
```

```python
class ComparisonRunner:
    def run(self, ctx):
        # Champion: 실제 실행
        champion_signal = self.champion.run(ctx)
        execute(champion_signal)

        # Challenger: shadow 실행 (로그만 기록)
        challenger_signal = self.challenger.run(ctx)
        log_shadow(challenger_signal)

        # 30일 후 성과 비교
        if days_elapsed >= config.comparison.switch_after_days:
            report = compare_performance(
                champion_log, challenger_log,
                metric=config.comparison.switch_metric
            )
            send_telegram(f"Champion vs Challenger 리포트:\n{report}")
            # 자동 교체는 하지 않음 — 리포트를 보고 수동 결정
```

## 의사결정 로그 (알고리즘 정보 포함)

```json
{
    "decision_id": "uuid",
    "ts_utc": "2026-02-16T09:05:00Z",
    "symbol": "005930",
    "market": "KR",
    "decision": "BUY",
    "score": 0.431,
    "algorithm": "ensemble",
    "algorithm_detail": {
        "mode": "weighted_vote",
        "member_signals": [
            {"algorithm": "sentiment_momentum", "decision": "BUY",  "score": 0.72, "weight": 0.20},
            {"algorithm": "technical_trend",    "decision": "BUY",  "score": 0.65, "weight": 0.25},
            {"algorithm": "mean_reversion",     "decision": "HOLD", "score": 0.10, "weight": 0.15},
            {"algorithm": "event_catalyst",     "decision": "BUY",  "score": 0.80, "weight": 0.20},
            {"algorithm": "volume_price",       "decision": "HOLD", "score":-0.05, "weight": 0.10},
            {"algorithm": "overnight_gap",      "decision": "SELL", "score":-0.40, "weight": 0.10}
        ],
        "regime": "trending_up"
    },
    "reason_codes": ["SM:BUY", "TF:BUY", "MR:HOLD", "EC:BUY", "VP:HOLD", "OG:SELL"],
    "risk_check": { "passed": true },
    "model_version": "ensemble_v1"
}
```

## 구현 우선순위

| 순서 | 알고리즘 | Phase | 사유 |
|------|---------|-------|------|
| 1 | Sentiment Momentum (SM) | 1 | 시스템 핵심. 뉴스 데이터만 있으면 동작 |
| 2 | Technical Trend (TF) | 1 | 시세 데이터만 있으면 동작. SM과 병렬 개발 가능 |
| 3 | Mean Reversion (MR) | 1 | TF와 동일 데이터 사용. 추가 구현 비용 낮음 |
| 4 | Event Catalyst (EC) | 2 | 이벤트 분류기 필요 (Phase 2 NLP) |
| 5 | Overnight Gap (OG) | 2 | 장전 루틴(05-pre-market.md) 완성 후 |
| 6 | Volume-Price (VP) | 2 | OBV/거래량 분석 추가 |
| 7 | Sector Correlation (SC) | 2 | 섹터 맵핑 데이터 필요 |
| 8 | Regime-Adaptive (RA) | 3 | 다른 알고리즘이 충분히 검증된 후 |
| — | Ensemble | 2 | 개별 알고리즘 3개 이상 준비 후 |
| — | Champion/Challenger | 3 | 앙상블 안정화 후 |

## 완료 기준

- [ ] BaseAlgorithm 인터페이스 + AlgorithmRouter 구현
- [ ] SM, TF, MR 3종 구현 + 단위 테스트
- [ ] settings.yaml에서 `active` 변경 시 알고리즘 교체 확인
- [ ] Ensemble 모드 (weighted_vote) 정상 동작
- [ ] 의사결정 로그에 알고리즘 상세 기록 확인
- [ ] EC, OG, VP, SC 4종 구현 (Phase 2)
- [ ] Regime-Adaptive 구현 (Phase 3)
- [ ] Champion/Challenger 비교 리포트 생성 확인

---

## Hybrid Update (2026-02-16)

### 1) Hybrid 실행 플로우
1. Numeric Stage: 기존 알고리즘 앙상블 점수 산출 (`numeric_score`)
2. Trigger Check: Agent 호출 조건 판정
3. Agent Stage: News/Technical/Regime/Portfolio Agent 병렬 실행
4. Fusion Stage: `final_score = alpha * numeric_score + (1-alpha) * agent_score`
5. Decision Stage: BUY/SELL/HOLD 결정 후 Risk Gate 전달

### 2) Agent 호출 조건
- `abs(numeric_score - buy_threshold) < near_threshold_margin`
- `abs(numeric_score - sell_threshold) < near_threshold_margin`
- 뉴스와 기술 신호 방향이 상충할 때
- 실적/규제/소송/M&A 등 고영향 이벤트 감지 시

### 3) 보유종목 기반 매도 제안 로직
- 입력: `manual_holdings_lots` + 현재가 + 뉴스/기술/체제 신호
- 출력: `SELL`, `REDUCE`, `HOLD`
- 예시 규칙:
  - 손절: 현재수익률 <= stop_loss 기준 -> `SELL`
  - 위험축소: 변동성 급증 + 신호 약화 -> `REDUCE`
  - 유지: 신호 중립/상향 + 리스크 통과 -> `HOLD`

### 4) 추천과 실행 분리
- 매도 제안은 `recommendation`으로 저장하고 즉시 주문하지 않는다.
- 사용자 확인 후에만 Execution 레이어에 주문 요청을 전달한다.

## Trade Ledger Update (2026-02-16)

### 보유종목 한정 매도 제안 규칙
1. `trade_ledger`에서 현재 보유 집합 계산
2. 분석 엔진은 보유 종목만 `sell_candidate_universe`로 구성
3. 비보유 종목은 매도 제안 로직에서 즉시 제외

### 의사코드
```python
holdings = get_current_holdings(user_id)   # net_quantity > 0
for symbol in market_universe:
    if symbol not in holdings:
        continue  # 매도 제안 금지
    recommendation = build_sell_recommendation(symbol, holdings[symbol])
```

---

## LangGraph Integration (2026-02-17)

> Hybrid Agent Overlay의 핵심 오케스트레이션을 LangGraph StateGraph로 구현한다.

### 적용 범위

LangGraph는 **분석 엔진의 Hybrid 실행 플로우 전체**를 하나의 StateGraph로 표현한다.
기존 수치 엔진(AlgorithmRouter, EnsembleRunner)은 그래프의 **노드 함수** 안에서 호출되며,
LangGraph는 그 위의 **오케스트레이션 레이어**로 동작한다.

```
기존 코드 (유지)          LangGraph (신규 레이어)
─────────────────       ──────────────────────────────────
BaseAlgorithm            AnalysisGraph (StateGraph)
AlgorithmRouter     →      ├── numeric_node (기존 코드 호출)
EnsembleRunner             ├── trigger_node
Signal, Context            ├── agent_fan_out (4종 병렬)
                           ├── fusion_node
                           ├── decision_node
                           └── risk_gate_node
```

### AnalysisState 정의

```python
from typing import TypedDict, Annotated
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
import operator

class AnalysisState(TypedDict):
    """그래프 전체에서 공유되는 상태"""
    # --- 입력 ---
    symbol: str
    market: str
    context: dict                          # AlgorithmContext 직렬화

    # --- Numeric Stage 결과 ---
    numeric_score: float                   # 앙상블 점수 (-1 ~ +1)
    numeric_decision: str                  # BUY / SELL / HOLD
    numeric_confidence: float
    member_signals: list[dict]             # 개별 알고리즘 결과

    # --- Trigger Check ---
    agent_required: bool                   # Agent 호출 필요 여부
    trigger_reasons: list[str]             # 트리거 사유

    # --- Agent Stage 결과 ---
    agent_news_result: dict | None
    agent_technical_result: dict | None
    agent_regime_result: dict | None
    agent_portfolio_result: dict | None
    agent_score: float | None
    agent_confidence: float | None

    # --- Fusion ---
    alpha: float                           # 동적 alpha
    final_score: float
    final_decision: str
    final_confidence: float

    # --- Risk Gate ---
    risk_passed: bool
    risk_reason: str
    action: str                            # EXECUTE / HOLD / BLOCKED

    # --- 메타 ---
    decision_id: str                       # UUID (감사 추적)
    created_at: str                        # ISO 8601
    errors: Annotated[list[str], operator.add]  # 누적 오류
```

### 그래프 구조

```
                    ┌─────────────────────────────────────────────────┐
                    │            AnalysisGraph                        │
                    │                                                 │
  START ──→ [numeric_node] ──→ [trigger_node] ──┬──→ [fusion_node]  │
                                                │         │          │
                          agent_required=True    │         │          │
                          ┌─────────────────────┘         │          │
                          ▼                               │          │
                  [agent_fan_out]                          │          │
                   ┌────┬────┬────┐                       │          │
                   │    │    │    │                        ▼          │
                [news][tech][reg][port]         [decision_node]      │
                   │    │    │    │                        │          │
                   └────┴────┴────┘                       ▼          │
                  [agent_fan_in] ──────────→     [risk_gate_node]    │
                                                          │          │
                                                          ▼          │
                                                        END          │
                    └─────────────────────────────────────────────────┘
```

### 노드 구현

#### 1. numeric_node — 수치 엔진 실행

```python
def numeric_node(state: AnalysisState) -> dict:
    """기존 AlgorithmRouter/EnsembleRunner를 호출하여 numeric_score 산출"""
    ctx = deserialize_context(state["context"])
    router = AlgorithmRouter(config)
    signal = router.run(ctx)

    return {
        "numeric_score": signal.score,
        "numeric_decision": signal.decision,
        "numeric_confidence": signal.confidence,
        "member_signals": [
            {"algorithm": s.algorithm, "decision": s.decision,
             "score": s.score, "weight": w}
            for s, w in signal.details.get("member_signals", [])
        ],
    }
```

#### 2. trigger_node — Agent 호출 판정

```python
def trigger_node(state: AnalysisState) -> dict:
    """Agent 호출이 필요한 상황인지 판정"""
    score = state["numeric_score"]
    cfg = config.analysis.hybrid.agent_trigger
    reasons = []

    # 임계값 근접: 매수/매도 경계에서 판단이 애매한 경우
    buy_th = config.analysis.signal.buy_threshold
    sell_th = config.analysis.signal.sell_threshold
    margin = cfg.near_threshold_margin

    if abs(score - buy_th) < margin:
        reasons.append("NEAR_BUY_THRESHOLD")
    if abs(score - sell_th) < margin:
        reasons.append("NEAR_SELL_THRESHOLD")

    # 신호 충돌: 감성 vs 기술 방향 불일치
    members = state["member_signals"]
    sm = next((m for m in members if m["algorithm"] == "sentiment_momentum"), None)
    tf = next((m for m in members if m["algorithm"] == "technical_trend"), None)
    if sm and tf and sm["score"] * tf["score"] < 0:
        reasons.append("SIGNAL_CONFLICT")

    # 고영향 이벤트 감지
    ctx = deserialize_context(state["context"])
    for news in ctx.news_events:
        if news.get("event_type") in cfg.high_impact_event_types:
            reasons.append(f"HIGH_IMPACT:{news['event_type'].upper()}")
            break

    return {
        "agent_required": len(reasons) > 0,
        "trigger_reasons": reasons,
    }
```

#### 3. agent_fan_out — 4종 전문 Agent 병렬 실행

```python
from langgraph.graph import Send

def agent_fan_out(state: AnalysisState) -> list[Send]:
    """4종 Agent를 병렬로 dispatch"""
    return [
        Send("agent_news",      state),
        Send("agent_technical",  state),
        Send("agent_regime",     state),
        Send("agent_portfolio",  state),
    ]
```

각 Agent 노드는 LLM을 호출하여 구조화된 판단을 반환한다:

```python
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field

class AgentJudgment(BaseModel):
    """Agent가 반환하는 구조화된 판단"""
    direction: str = Field(description="BUY / SELL / HOLD")
    score: float = Field(ge=-1.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    key_factors: list[str]

# --- News Agent ---
def agent_news(state: AnalysisState) -> dict:
    """뉴스 맥락을 LLM으로 심층 분석"""
    ctx = deserialize_context(state["context"])
    parser = PydanticOutputParser(pydantic_object=AgentJudgment)

    prompt = ChatPromptTemplate.from_messages([
        ("system", NEWS_AGENT_SYSTEM_PROMPT),
        ("human", """
종목: {symbol} ({market})
현재 수치 엔진 점수: {numeric_score}
최근 뉴스 {news_count}건:
{news_summary}

위 뉴스를 종합하여 매매 판단을 내려주세요.
{format_instructions}
"""),
    ])

    chain = prompt | llm_fast | parser
    try:
        result = chain.invoke({
            "symbol": state["symbol"],
            "market": state["market"],
            "numeric_score": state["numeric_score"],
            "news_count": len(ctx.news_events),
            "news_summary": format_news_for_llm(ctx.news_events[:10]),
            "format_instructions": parser.get_format_instructions(),
        })
        return {"agent_news_result": result.model_dump()}
    except Exception as e:
        return {"agent_news_result": None, "errors": [f"NEWS_AGENT_ERROR: {e}"]}


# --- Technical Agent ---
def agent_technical(state: AnalysisState) -> dict:
    """기술 지표 패턴을 LLM으로 해석"""
    ctx = deserialize_context(state["context"])
    prompt = ChatPromptTemplate.from_messages([
        ("system", TECHNICAL_AGENT_SYSTEM_PROMPT),
        ("human", """
종목: {symbol} | RSI: {rsi} | MACD: {macd} | 볼린저 위치: {bb_pos}
SMA20: {sma20} vs SMA50: {sma50} | 거래량 비율: {vol_ratio}
최근 5분봉 20개: {bars_summary}
{format_instructions}
"""),
    ])
    chain = prompt | llm_fast | parser
    try:
        result = chain.invoke(build_technical_context(ctx, state))
        return {"agent_technical_result": result.model_dump()}
    except Exception as e:
        return {"agent_technical_result": None, "errors": [f"TECH_AGENT_ERROR: {e}"]}


# --- Regime Agent ---
def agent_regime(state: AnalysisState) -> dict:
    """현재 시장 체제를 판단하고 적합한 전략 제안"""
    ctx = deserialize_context(state["context"])
    prompt = ChatPromptTemplate.from_messages([
        ("system", REGIME_AGENT_SYSTEM_PROMPT),
        ("human", """
시장: {market} | VIX: {vix} | 현재 체제 판정: {regime}
KOSPI/S&P 최근 추이: {index_summary}
수치 엔진 체제 판정과 당신의 판정이 다르면 그 이유를 설명하세요.
{format_instructions}
"""),
    ])
    chain = prompt | llm_fast | parser
    try:
        result = chain.invoke(build_regime_context(ctx, state))
        return {"agent_regime_result": result.model_dump()}
    except Exception as e:
        return {"agent_regime_result": None, "errors": [f"REGIME_AGENT_ERROR: {e}"]}


# --- Portfolio Agent ---
def agent_portfolio(state: AnalysisState) -> dict:
    """보유 포지션 맥락에서 신규 진입/추가/축소 판단"""
    ctx = deserialize_context(state["context"])
    prompt = ChatPromptTemplate.from_messages([
        ("system", PORTFOLIO_AGENT_SYSTEM_PROMPT),
        ("human", """
종목: {symbol} | 보유 여부: {has_position}
포지션: 수량 {qty}, 평단 {avg_cost}, 수익률 {pnl_pct}%
포트폴리오: 현금비율 {cash_pct}%, 보유 {pos_count}종목
리스크 여력: 일일 {daily_remaining}%, 주간 {weekly_remaining}%
{format_instructions}
"""),
    ])
    chain = prompt | llm_fast | parser
    try:
        result = chain.invoke(build_portfolio_context(ctx, state))
        return {"agent_portfolio_result": result.model_dump()}
    except Exception as e:
        return {"agent_portfolio_result": None, "errors": [f"PORT_AGENT_ERROR: {e}"]}
```

#### 4. agent_fan_in — Agent 결과 집계

```python
def agent_fan_in(state: AnalysisState) -> dict:
    """4종 Agent 결과를 하나의 agent_score로 합산"""
    results = []
    weights = config.analysis.langgraph.agent_weights

    for key, weight_key in [
        ("agent_news_result",      "news"),
        ("agent_technical_result", "technical"),
        ("agent_regime_result",    "regime"),
        ("agent_portfolio_result", "portfolio"),
    ]:
        result = state.get(key)
        if result is not None:
            results.append((result["score"], result["confidence"], weights[weight_key]))

    if not results:
        # 모든 Agent 실패 → fallback
        return {
            "agent_score": None,
            "agent_confidence": None,
            "errors": ["ALL_AGENTS_FAILED"],
        }

    # 신뢰도 가중 평균
    weighted_sum = sum(s * c * w for s, c, w in results)
    total_weight = sum(c * w for _, c, w in results)
    agent_score = weighted_sum / total_weight if total_weight > 0 else 0
    agent_confidence = sum(c * w for _, c, w in results) / sum(w for _, _, w in results)

    return {
        "agent_score": agent_score,
        "agent_confidence": agent_confidence,
    }
```

#### 5. fusion_node — 수치 + Agent 점수 융합

```python
def fusion_node(state: AnalysisState) -> dict:
    """numeric_score와 agent_score를 alpha 블렌딩으로 합산"""
    numeric = state["numeric_score"]

    # Agent를 호출하지 않았거나 전부 실패한 경우
    if not state["agent_required"] or state.get("agent_score") is None:
        return {
            "alpha": 1.0,
            "final_score": numeric,
            "final_confidence": state["numeric_confidence"],
        }

    agent = state["agent_score"]

    # 동적 alpha 결정
    alpha = compute_dynamic_alpha(state)

    final_score = alpha * numeric + (1 - alpha) * agent
    final_confidence = (
        alpha * state["numeric_confidence"] +
        (1 - alpha) * state["agent_confidence"]
    )

    return {
        "alpha": alpha,
        "final_score": final_score,
        "final_confidence": final_confidence,
    }


def compute_dynamic_alpha(state: AnalysisState) -> float:
    """시장 상황에 따라 alpha를 동적 조정"""
    cfg = config.analysis.hybrid
    ctx = deserialize_context(state["context"])

    # 기본값
    alpha = cfg.alpha_default  # 0.7

    # VIX 높거나 변동성 과열 → agent 비중 증가 (alpha 감소)
    if ctx.regime == "volatile":
        alpha = min(alpha, cfg.alpha_volatile)  # 0.5

    # 뉴스 급증 구간 → agent 비중 증가
    if len(ctx.news_events) > 10:
        alpha = min(alpha, cfg.alpha_news_spike)  # 0.4

    # Agent 자체 신뢰도가 낮으면 → numeric 신뢰 (alpha 증가)
    if state.get("agent_confidence", 0) < 0.4:
        alpha = max(alpha, 0.85)

    return alpha
```

#### 6. decision_node — 최종 결정

```python
def decision_node(state: AnalysisState) -> dict:
    """final_score → BUY/SELL/HOLD 결정"""
    score = state["final_score"]
    buy_th = config.analysis.signal.buy_threshold
    sell_th = config.analysis.signal.sell_threshold

    if score >= buy_th:
        decision = "BUY"
    elif score <= sell_th:
        decision = "SELL"
    else:
        decision = "HOLD"

    return {"final_decision": decision}
```

#### 7. risk_gate_node — 리스크 게이트

```python
def risk_gate_node(state: AnalysisState) -> dict:
    """07-risk-management의 3계층 리스크 체크를 실행"""
    if state["final_decision"] == "HOLD":
        return {"risk_passed": True, "risk_reason": "HOLD_NO_CHECK", "action": "HOLD"}

    ctx = deserialize_context(state["context"])
    signal = {
        "symbol": state["symbol"],
        "market": state["market"],
        "decision": state["final_decision"],
        "score": state["final_score"],
    }

    passed, reason = risk_gate.check(signal, ctx.portfolio)

    if passed:
        action = "EXECUTE"
    else:
        action = "BLOCKED"

    return {"risk_passed": passed, "risk_reason": reason, "action": action}
```

### 그래프 빌드

```python
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver

def build_analysis_graph() -> StateGraph:
    graph = StateGraph(AnalysisState)

    # 노드 등록
    graph.add_node("numeric",        numeric_node)
    graph.add_node("trigger",        trigger_node)
    graph.add_node("agent_news",     agent_news)
    graph.add_node("agent_technical", agent_technical)
    graph.add_node("agent_regime",   agent_regime)
    graph.add_node("agent_portfolio", agent_portfolio)
    graph.add_node("agent_fan_in",   agent_fan_in)
    graph.add_node("fusion",         fusion_node)
    graph.add_node("decision",       decision_node)
    graph.add_node("risk_gate",      risk_gate_node)

    # 엣지 연결
    graph.add_edge(START, "numeric")
    graph.add_edge("numeric", "trigger")

    # 조건부 분기: Agent 필요 여부
    graph.add_conditional_edges(
        "trigger",
        lambda s: "agent" if s["agent_required"] else "skip",
        {
            "agent": "agent_news",      # Agent fan-out 시작
            "skip":  "fusion",           # Agent 건너뜀
        },
    )

    # Agent 4종 병렬 → fan-in
    # (LangGraph의 Send API 또는 동일 입력 노드 병렬 배치)
    for agent_node in ["agent_news", "agent_technical", "agent_regime", "agent_portfolio"]:
        graph.add_edge("trigger", agent_node)    # trigger → 4종 동시
        graph.add_edge(agent_node, "agent_fan_in")

    graph.add_edge("agent_fan_in", "fusion")
    graph.add_edge("fusion", "decision")
    graph.add_edge("decision", "risk_gate")
    graph.add_edge("risk_gate", END)

    # 체크포인터 (SQLite — VM 로컬)
    checkpointer = SqliteSaver.from_conn_string("data/langgraph_checkpoints.db")

    return graph.compile(checkpointer=checkpointer)


# 사용
analysis_graph = build_analysis_graph()

result = analysis_graph.invoke(
    {
        "symbol": "005930",
        "market": "KR",
        "context": serialize_context(ctx),
        "decision_id": str(uuid4()),
        "created_at": datetime.utcnow().isoformat(),
        "errors": [],
    },
    config={"configurable": {"thread_id": f"005930-KR-{timestamp}"}},
)

# result["action"] == "EXECUTE" | "HOLD" | "BLOCKED"
```

### Agent 프롬프트 관리

Agent 시스템 프롬프트는 별도 파일로 관리하여 코드 변경 없이 조정한다:

```
config/prompts/
├── news_agent.txt          ← NEWS_AGENT_SYSTEM_PROMPT
├── technical_agent.txt     ← TECHNICAL_AGENT_SYSTEM_PROMPT
├── regime_agent.txt        ← REGIME_AGENT_SYSTEM_PROMPT
└── portfolio_agent.txt     ← PORTFOLIO_AGENT_SYSTEM_PROMPT
```

각 프롬프트는 다음 원칙을 따른다:
- **역할 명시**: "당신은 {역할} 전문 분석가입니다"
- **출력 형식 강제**: AgentJudgment Pydantic 스키마 준수
- **범위 제한**: 자기 영역 외 판단 금지 (News Agent는 기술 지표 언급 금지)
- **근거 필수**: reasoning 필드에 판단 근거 3줄 이상

### 체크포인팅 & 재시도 전략

```python
# 체크포인터: SQLite (VM 로컬 디스크)
# - 장애 발생 시 마지막 성공 노드부터 재개
# - thread_id = "{symbol}-{market}-{timestamp}"로 각 분석 건 격리

# 노드별 타임아웃
TIMEOUT_CONFIG = {
    "numeric":    5_000,    # 5초 (수치 계산)
    "trigger":    1_000,    # 1초 (규칙 판정)
    "agent_*":    3_000,    # 3초 (LLM API 호출) — settings.yaml 연동
    "fusion":     1_000,    # 1초
    "decision":     500,    # 0.5초
    "risk_gate":  1_000,    # 1초
}

# Agent 노드 타임아웃 시 → 해당 Agent 결과를 None으로 처리
# 모든 Agent 실패 시 → agent_score = None → fusion에서 numeric_only 폴백
```

### 감사 로그 자동 기록

LangGraph의 실행 결과를 BigQuery `decision_logs`에 자동 저장:

```python
def save_decision_log(result: AnalysisState):
    """그래프 실행 결과 전체를 감사 로그로 기록"""
    log = {
        "decision_id": result["decision_id"],
        "ts_utc": result["created_at"],
        "symbol": result["symbol"],
        "market": result["market"],
        # Numeric
        "numeric_score": result["numeric_score"],
        "numeric_decision": result["numeric_decision"],
        "member_signals": result["member_signals"],
        # Agent
        "agent_required": result["agent_required"],
        "trigger_reasons": result["trigger_reasons"],
        "agent_news": result.get("agent_news_result"),
        "agent_technical": result.get("agent_technical_result"),
        "agent_regime": result.get("agent_regime_result"),
        "agent_portfolio": result.get("agent_portfolio_result"),
        "agent_score": result.get("agent_score"),
        # Fusion
        "alpha": result["alpha"],
        "final_score": result["final_score"],
        "final_decision": result["final_decision"],
        # Risk
        "risk_passed": result["risk_passed"],
        "risk_reason": result["risk_reason"],
        "action": result["action"],
        # Meta
        "errors": result["errors"],
        "graph_version": "analysis_v1",
    }
    bigquery_client.insert_rows_json("decision_logs", [log])
```