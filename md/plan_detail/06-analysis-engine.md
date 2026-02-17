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