# 10. 종목 유니버스 관리

> Phase 2 - Track B | 병렬 진행 가능 | 소요: Week 5~8

## 3-Tier 구조

```
┌─────────────────────────────────────────────────────────┐
│  Tier 1: 핵심 추적 (KR 30 + US 30 = 60종목)              │
│  5분 주기 시세+뉴스 수집, 전수 분석, 매매 신호 생성 대상      │
├─────────────────────────────────────────────────────────┤
│  Tier 2: 감시 (KR 50 + US 50 = 100종목)                  │
│  5분 주기 시세 수집, 뉴스 키워드 스캔만                      │
│  조건 충족 시 Tier 1로 승격                                │
├─────────────────────────────────────────────────────────┤
│  Tier 3: 일별 스크리닝 (전체 시장)                          │
│  장 마감 후 일봉 기준 스크리닝                               │
│  조건 충족 시 Tier 2로 편입                                │
└─────────────────────────────────────────────────────────┘
```

## Tier 1 초기 선정 기준

### KR 30종목

| 기준 | 설정 키 | 기본값 |
|------|---------|--------|
| 시가총액 순위 | `universe.tier1.kr.min_market_cap_rank` | 상위 50위 |
| 일평균 거래대금 | `universe.tier1.kr.min_daily_trading_value_krw` | 100억+ |
| 섹터당 최대 | `universe.tier1.kr.max_per_sector` | 5종목 |
| 제외 | — | 관리종목, 투자경고, 스팩 |

### US 30종목

| 기준 | 설정 키 | 기본값 |
|------|---------|--------|
| 시가총액 순위 | `universe.tier1.us.min_market_cap_rank` | 상위 50위 |
| 일평균 거래량 | `universe.tier1.us.min_daily_volume` | 500만주+ |
| 섹터당 최대 | `universe.tier1.us.max_per_sector` | 5종목 |
| 제외 | — | ADR, 소형주 |

### 수동 지정

`settings.yaml`에서 직접 종목 지정 가능:

```yaml
universe:
  tier1:
    kr:
      symbols:
        - "005930"   # 삼성전자
        - "000660"   # SK하이닉스
        - "373220"   # LG에너지솔루션
        # ... 30종목
    us:
      symbols:
        - "AAPL"
        - "MSFT"
        - "NVDA"
        # ... 30종목
```

`symbols` 배열이 비어있으면 기준에 따라 자동 선정.

## 동적 승격/강등

### Tier 2 → Tier 1 승격 조건

`settings.yaml`의 `universe.promotion` 섹션:

```python
def check_promotion(symbol: str) -> str | None:
    """하나 이상 충족 시 승격"""

    # 뉴스 급증: 24시간 내 뉴스 수가 평소 대비 3배
    if news_count_24h(symbol) > avg_news_count(symbol, days=30) * 3.0:
        return "NEWS_SPIKE"

    # 거래량 급증: 5일 평균 대비 3배
    if volume_today(symbol) > avg_volume(symbol, days=5) * 3.0:
        return "VOLUME_SPIKE"

    # 변동성 상위 10%
    if volatility_rank(symbol) <= 10:
        return "VOLATILITY_JUMP"

    # 실적 발표 D-7 이내
    if days_to_earnings(symbol) <= 7:
        return "EARNINGS_SOON"

    # 감성 점수 급변
    if abs(sentiment_change_24h(symbol)) > 0.5:
        return "SENTIMENT_SHIFT"

    return None
```

### Tier 1 → Tier 2 강등 조건

`settings.yaml`의 `universe.demotion` 섹션:

```python
def check_demotion(symbol: str) -> str | None:
    # 30일간 매매 신호 0건
    if signal_count(symbol, days=30) == 0:
        return "NO_SIGNAL_30D"

    # 거래대금 기준 미달 연속 10일
    if low_volume_days(symbol) >= 10:
        return "LOW_VOLUME"

    # 포지션 청산 후 쿨다운 7일
    if recently_closed(symbol, days=7):
        return "POST_CLOSE_COOLDOWN"

    return None
```

## Tier 3 스크리닝 (장 마감 후 일배치)

```python
def daily_screen(market: str) -> list[str]:
    """전체 시장 일봉 기반 스크리닝 → Tier 2 편입 후보"""
    all_symbols = get_all_symbols(market)
    candidates = []

    for symbol in all_symbols:
        daily = get_daily_bar(symbol)

        # 거래량 돌파: 20일 평균 대비 5배
        if daily.volume > avg_volume_20d(symbol) * 5:
            candidates.append((symbol, "VOLUME_BREAKOUT"))

        # 52주 신고가/신저가
        if daily.close >= high_52w(symbol) or daily.close <= low_52w(symbol):
            candidates.append((symbol, "PRICE_BREAKOUT"))

        # RSI 극단값
        rsi = compute_daily_rsi(symbol)
        if rsi < 25 or rsi > 75:
            candidates.append((symbol, "RSI_EXTREME"))

        # 갭 5% 이상
        prev_close = get_prev_close(symbol)
        if abs(daily.open - prev_close) / prev_close > 0.05:
            candidates.append((symbol, "GAP"))

    return candidates
```

## 유니버스 변경 기록

```sql
-- BigQuery: stock_universe 테이블에 tier 변경 이력 보존
-- tier_changed_at, promote_reason 필드로 추적

-- 변경 이력 조회
SELECT symbol, market, tier, tier_changed_at, promote_reason
FROM stock_trading.stock_universe
WHERE tier_changed_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
ORDER BY tier_changed_at DESC;
```

## 실행 주기

| 작업 | 시점 | 설명 |
|------|------|------|
| Tier 1↔2 승격/강등 | 장 마감 후 (매일) | 조건 기반 자동 |
| Tier 3 스크리닝 | 장 마감 후 (매일) | 전체 시장 스캔 |
| 기준 재검토 | 월 1회 | 시가총액/거래량 기준 갱신 |
| 수동 조정 | 수시 | settings.yaml 수정 |

## 리소스 소비

| Tier | 종목 수 | BigQuery (GB/년) | LLM ($/일) | Redis (MB) |
|------|---------|-----------------|-----------|-----------|
| 1 | 60 | 0.15 | ~$0.18 | ~1.4 |
| 2 | 100 | 0.25 | $0 (키워드만) | ~2.4 |
| 3 | 전체 | 0.05 (일봉) | $0 | 0 |
| **합계** | 160 실시간 | **~0.45** | **~$0.18** | **~3.8** |

## 완료 기준

- [ ] Tier 1 초기 종목 60개 선정 완료 (KR 30 + US 30)
- [ ] Tier 2 종목 100개 선정 완료
- [ ] 승격/강등 로직 정상 동작
- [ ] Tier 3 일배치 스크리닝 정상
- [ ] BigQuery stock_universe 테이블 업데이트 정상
- [ ] settings.yaml 수동 종목 지정 반영 확인
