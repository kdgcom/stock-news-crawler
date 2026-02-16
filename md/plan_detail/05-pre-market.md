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
