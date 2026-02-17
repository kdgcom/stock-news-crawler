# 리스크 관리 및 규정 준수

## 1. 리스크 관리가 최우선인 이유

자동 트레이딩 시스템에서 **리스크 관리는 수익 전략보다 중요하다**. 아무리 좋은 알고리즘도 한 번의 치명적 손실로 전체 자본을 잃을 수 있다. 특히 AI/LLM이 판단에 관여하는 시스템에서는 환각(hallucination), 학습 데이터 편향, 예측 불가능한 시장 이벤트에 대한 대비가 필수적이다.

---

## 2. 리스크 관리 계층 구조

```
┌───────────────────────────────────────────────────┐
│             Level 1: 시스템 안전장치               │
│   하드코딩된 한도 - 어떤 AI 판단도 이를 무시 불가    │
│   ┌─────────────────────────────────────────────┐ │
│   │ - 단일 주문 최대 금액                        │ │
│   │ - 일일 최대 손실 한도                        │ │
│   │ - 최대 포지션 수                             │ │
│   │ - 비상 정지 (Kill Switch)                    │ │
│   └─────────────────────────────────────────────┘ │
├───────────────────────────────────────────────────┤
│             Level 2: 동적 리스크 관리              │
│   시장 상황에 따라 조정되는 제한                    │
│   ┌─────────────────────────────────────────────┐ │
│   │ - VIX/변동성 기반 포지션 축소                 │ │
│   │ - 연속 손실 시 자동 쿨다운                    │ │
│   │ - 섹터/국가 집중도 제한                       │ │
│   └─────────────────────────────────────────────┘ │
├───────────────────────────────────────────────────┤
│             Level 3: AI 판단 검증                  │
│   AI의 매매 결정에 대한 사후 검증                   │
│   ┌─────────────────────────────────────────────┐ │
│   │ - 신호 신뢰도 임계값                         │ │
│   │ - 이상 거래 패턴 감지                        │ │
│   │ - 분석 근거 검증                             │ │
│   └─────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────┘
```

---

## 3. 하드 리미트 (절대 한도)

코드에 하드코딩되어 **어떤 조건에서도 초과할 수 없는** 안전 한도.

```python
class HardLimits:
    """절대적 안전 한도 - 이 값들은 코드에서만 수정 가능"""

    # ─── 주문 한도 ───
    MAX_SINGLE_ORDER_KRW = 5_000_000        # 단일 주문 최대 500만원
    MAX_SINGLE_ORDER_USD = 3_000            # 단일 주문 최대 $3,000
    MAX_ORDERS_PER_DAY = 50                 # 일일 최대 주문 횟수

    # ─── 손실 한도 ───
    MAX_DAILY_LOSS_PCT = -0.03              # 일일 최대 손실 -3%
    MAX_WEEKLY_LOSS_PCT = -0.05             # 주간 최대 손실 -5%
    MAX_TOTAL_DRAWDOWN_PCT = -0.15          # 전체 MDD 한도 -15%

    # ─── 포지션 한도 ───
    MAX_SINGLE_STOCK_PCT = 0.10             # 단일 종목 최대 10%
    MAX_TOTAL_POSITIONS = 20                # 최대 보유 종목 수
    MIN_CASH_RESERVE_PCT = 0.20             # 최소 현금 비율 20%

    # ─── 시스템 한도 ───
    MAX_LLM_CALLS_PER_HOUR = 100            # 시간당 LLM 호출 한도
    MAX_LLM_DAILY_COST_USD = 20.0           # 일일 LLM 비용 한도
    ORDER_TIMEOUT_SECONDS = 30              # 주문 응답 타임아웃
```

### 3.1 Kill Switch (비상 정지)

```python
class KillSwitch:
    """비상 정지 시스템 - 모든 거래 즉시 중단"""

    def __init__(self):
        self.is_active = False
        self.reason = None

    def activate(self, reason: str):
        self.is_active = True
        self.reason = reason
        self._cancel_all_pending_orders()
        self._notify_critical(f"KILL SWITCH 작동: {reason}")
        self._log_audit("kill_switch_activated", reason=reason)

    def check(self) -> bool:
        """모든 거래 전 호출 - True이면 거래 불가"""
        return self.is_active

    AUTO_TRIGGER_CONDITIONS = [
        "일일 손실 한도 초과",
        "MDD 한도 초과",
        "증권사 API 연속 실패 5회",
        "시스템 이상 동작 감지",
        "수동 작동 (사용자)",
    ]
```

---

## 4. 손절매 (Stop-Loss) 전략

### 4.1 개별 종목 손절

```python
class StopLossManager:
    # 기본 손절 라인
    DEFAULT_STOP_LOSS_PCT = -0.05           # -5% 손절
    TRAILING_STOP_PCT = -0.03               # 3% 트레일링 스탑

    def check_stop_loss(self, position: Position) -> bool:
        """포지션의 손절 조건 확인"""

        current_price = self.get_current_price(position.ticker)
        entry_price = position.avg_price
        pnl_pct = (current_price - entry_price) / entry_price

        # 1. 고정 손절
        if pnl_pct <= self.DEFAULT_STOP_LOSS_PCT:
            return True  # 손절 실행

        # 2. 트레일링 스탑 (수익 구간에서 고점 대비 하락 시)
        if position.highest_price > entry_price:
            from_high_pct = (current_price - position.highest_price) / position.highest_price
            if from_high_pct <= self.TRAILING_STOP_PCT:
                return True  # 트레일링 스탑 실행

        return False

    def check_time_stop(self, position: Position) -> bool:
        """보유 기간 기반 손절 - 일정 기간 내 목표 미달 시"""
        holding_days = (datetime.now() - position.entry_date).days

        # 5일 이상 보유 + 수익률 -2% 미만이면 정리
        if holding_days >= 5 and position.pnl_pct < -0.02:
            return True

        return False
```

### 4.2 포트폴리오 레벨 손절

```python
class PortfolioStopLoss:
    def check_portfolio_risk(self) -> RiskAction:
        daily_pnl = self.calculate_daily_pnl()
        weekly_pnl = self.calculate_weekly_pnl()
        total_mdd = self.calculate_mdd()

        # 1단계: 경고 (-2% 일일)
        if daily_pnl < -0.02:
            return RiskAction(
                level="WARNING",
                action="신규 매수 50% 축소",
                message="일일 손실 -2% 접근"
            )

        # 2단계: 매수 중단 (-3% 일일)
        if daily_pnl < -0.03:
            return RiskAction(
                level="HALT_BUY",
                action="금일 신규 매수 전면 중단",
                message="일일 손실 한도 도달"
            )

        # 3단계: 전체 중단 (-15% MDD)
        if total_mdd < -0.15:
            return RiskAction(
                level="KILL_SWITCH",
                action="전체 거래 중단, 포지션 정리 검토",
                message="MDD 한도 초과"
            )

        return RiskAction(level="NORMAL", action="정상 운영")
```

---

## 5. AI 판단 검증

### 5.1 AI 환각(Hallucination) 방어

LLM은 때때로 사실과 다른 분석을 생성할 수 있다. 이를 방어하기 위한 장치:

```python
class AIValidation:
    def validate_sentiment(self, result: SentimentResult, article: NewsArticle) -> bool:
        """AI 감성 분석 결과 검증"""

        # 1. 신뢰도 임계값
        if result.confidence < 0.6:
            return False  # 낮은 신뢰도 결과 무시

        # 2. 극단적 점수 검증 (±0.9 이상이면 추가 검증)
        if abs(result.score) > 0.9:
            # 다른 모델로 교차 검증
            cross_check = self.cross_validate(article)
            if abs(result.score - cross_check.score) > 0.5:
                return False  # 모델 간 의견 불일치 → 보수적 판단

        # 3. 언급된 종목코드 실재 여부 확인
        for ticker in result.affected_tickers:
            if not self.is_valid_ticker(ticker):
                return False  # 존재하지 않는 종목코드

        return True

    def validate_trading_signal(self, signal: TradingDecision) -> bool:
        """매매 신호의 합리성 검증"""

        # 1. 근거가 최소 2개 이상인지
        if len(signal.reasons) < 2:
            return False

        # 2. 모든 분석이 같은 방향인지 (일부 불일치는 허용)
        directions = [r.direction for r in signal.reasons]
        agreement_ratio = max(directions.count("BUY"), directions.count("SELL")) / len(directions)
        if agreement_ratio < 0.6:
            return False  # 분석 간 합의 부족

        # 3. 시장 상황과 모순되지 않는지
        # (예: 시장 전체 급락 중 개별 종목 강한 매수 시그널)
        market_context = self.get_market_context()
        if market_context.is_crash and signal.action == "STRONG_BUY":
            signal.confidence *= 0.5  # 신뢰도 감소
            signal.requires_manual_review = True

        return True
```

### 5.2 이상 거래 패턴 감지

```python
class AnomalyDetector:
    def check_anomalies(self, signal: TradingDecision) -> list[str]:
        warnings = []

        # 1. 동일 종목 반복 매매 (과잉 거래)
        recent_trades = self.get_recent_trades(signal.ticker, hours=24)
        if len(recent_trades) >= 5:
            warnings.append("24시간 내 동일 종목 5회 이상 거래 시도")

        # 2. 장 시작/마감 직전 대량 주문
        now = datetime.now()
        if now.hour == 9 and now.minute < 5:
            warnings.append("장 시작 5분 이내 주문 - 변동성 주의")
        if now.hour == 15 and now.minute > 20:
            warnings.append("장 마감 10분 이내 주문 - 유동성 주의")

        # 3. 평소 대비 이상 수량
        avg_quantity = self.get_average_order_quantity(signal.ticker)
        if signal.quantity > avg_quantity * 3:
            warnings.append("평소 대비 3배 이상 수량")

        return warnings
```

---

## 6. 시장별 리스크 고려사항

### 6.1 국내 시장 (KRX)

| 리스크 | 대응 |
|--------|------|
| **가격 제한폭 (±30%)** | 상한가/하한가 근접 시 매매 자제 |
| **VI (변동성 완화장치)** | VI 발동 종목 자동 제외 |
| **공매도 제한** | 숏 포지션 불가 시 현금화만 가능 |
| **동시호가 (08:30~09:00, 15:20~15:30)** | 동시호가 시간 주문 제한 |
| **서킷브레이커** | 발동 시 모든 신규 주문 중단 |
| **배당락/권리락** | 이벤트 전후 매매 로직 특별 처리 |

### 6.2 미국 시장 (NYSE/NASDAQ)

| 리스크 | 대응 |
|--------|------|
| **가격 제한 없음** | 손절 라인 더 보수적으로 설정 |
| **프리마켓/애프터마켓** | 유동성 낮은 확장 거래 시간 매매 자제 |
| **LULD (Limit Up-Limit Down)** | 거래 일시 중단 감지 및 대응 |
| **환율 변동** | USD/KRW 환율 리스크 모니터링 |
| **서머타임** | 거래 시간 자동 조정 (3월, 11월) |
| **실적 발표 시즌** | Earnings 전후 변동성 대비 포지션 축소 |

### 6.3 환율 리스크

미국 주식 투자 시 환율 변동이 수익에 직접 영향을 미친다.

```python
class FxRiskManager:
    def check_fx_exposure(self) -> FxRiskReport:
        usd_positions = self.get_usd_denominated_positions()
        total_usd_exposure = sum(p.market_value_usd for p in usd_positions)

        # 총 자산 대비 USD 노출 비율
        total_capital_krw = self.get_total_capital_krw()
        usd_exposure_pct = (total_usd_exposure * self.get_usd_krw_rate()) / total_capital_krw

        return FxRiskReport(
            usd_exposure_pct=usd_exposure_pct,
            warning=usd_exposure_pct > 0.7,  # 70% 초과 시 경고
            current_rate=self.get_usd_krw_rate(),
            rate_change_30d=self.get_rate_change(days=30),
        )
```

---

## 7. 규정 준수 (Compliance)

### 7.1 국내 관련 법규

| 법규 | 핵심 내용 | 시스템 대응 |
|------|-----------|------------|
| **자본시장법** | 시세조종, 부정거래 금지 | 이상 거래 패턴 자동 감지 |
| **전자금융거래법** | 전자적 거래의 안전성 확보 | API 키 암호화 관리, 접근 로그 |
| **개인정보보호법** | 개인 금융정보 보호 | 데이터 암호화, 접근 제한 |

**주의사항:**
- 개인의 자동매매 프로그램 사용 자체는 합법
- 단, 시세조종(주가 조작), 허위 호가, 통정매매는 불법
- API 이용약관에서 허용하는 범위 내에서만 사용
- 세금 신고: 국내 주식 양도소득세 (대주주), 해외 주식 양도소득세 (250만원 초과)

### 7.2 미국 관련 법규

| 법규 | 핵심 내용 | 시스템 대응 |
|------|-----------|------------|
| **Pattern Day Trader 규정** | 5영업일 내 4회 이상 데이 트레이드 시 $25,000 이상 필요 | 단타 빈도 모니터링 |
| **Wash Sale Rule** | 30일 이내 손실 매도 후 재매수 시 세금 혜택 불가 | 매매 기록 자동 추적 |
| **SEC 규정** | 내부자 거래, 시세조종 금지 | 공시 전 뉴스 기반 매매 신중 처리 |

### 7.3 감사 추적 (Audit Trail)

모든 매매 결정의 근거를 영구 보존한다.

```python
class AuditLogger:
    """변경 불가능한 감사 로그"""

    def log_decision(self, decision: TradingDecision):
        audit_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "decision_id": str(uuid4()),
            "ticker": decision.ticker,
            "action": decision.action,
            "quantity": decision.quantity,
            "price": decision.target_price,

            # 판단 근거 전체 기록
            "sentiment_analysis": decision.sentiment_detail,
            "technical_analysis": decision.technical_detail,
            "fundamental_analysis": decision.fundamental_detail,
            "news_sources": [n.url for n in decision.source_news],

            # AI 판단 기록
            "llm_model": decision.llm_model,
            "llm_prompt": decision.llm_prompt,       # 사용된 프롬프트
            "llm_response": decision.llm_response,   # LLM 원문 응답

            # 리스크 검증 기록
            "risk_checks": decision.risk_check_results,
            "final_approval": decision.approved,
        }

        # MongoDB에 저장 (별도 audit 컬렉션, write-once)
        self.audit_collection.insert_one(audit_entry)
```

---

## 8. 모의투자 테스트 체크리스트

실전 투자 전 반드시 모의투자에서 검증해야 할 항목:

### 8.1 기능 검증
- [ ] 뉴스 크롤링이 정상적으로 동작하는가
- [ ] 감성 분석 결과가 합리적인가 (수동 확인 50건 이상)
- [ ] 기술적 지표 계산이 정확한가 (엑셀/차트와 비교)
- [ ] 매매 시그널이 적절한 빈도로 발생하는가
- [ ] 주문이 정상적으로 체결되는가
- [ ] 손절/익절 로직이 정확히 작동하는가

### 8.2 리스크 검증
- [ ] Kill Switch가 정상 작동하는가
- [ ] 일일 손실 한도 초과 시 거래가 중단되는가
- [ ] 단일 종목 비중 한도가 적용되는가
- [ ] WebSocket 끊김 시 자동 복구되는가
- [ ] API 장애 시 안전 모드로 전환되는가

### 8.3 성과 검증
- [ ] 최소 3개월 모의투자 수행
- [ ] 벤치마크(KOSPI, S&P 500) 대비 성과 비교
- [ ] MDD가 -15% 이내인가
- [ ] 승률 55% 이상인가
- [ ] 손익비 1.5 이상인가

### 8.4 실전 전환 조건
모의투자에서 아래 **모든 조건**을 만족해야 실전 전환:

1. 3개월 이상 안정적 운영 (시스템 가동률 99% 이상)
2. 벤치마크 수익률 초과
3. MDD -15% 이내 유지
4. Kill Switch 및 리스크 관리 장치 정상 작동 확인
5. 모든 감사 로그 정상 기록

---

## 9. 실전 투자 전환 시 단계적 접근

```
Step 1: 소액 (총 자본의 5%)으로 1개월 운영
    ↓ 성과 검증 통과
Step 2: 자본 10%로 증액, 1개월 운영
    ↓ 성과 검증 통과
Step 3: 자본 30%로 증액, 2개월 운영
    ↓ 성과 검증 통과
Step 4: 목표 자본 투입 (단, 전체 자산의 50% 초과 금지 권장)
```

**각 단계 사이 검증 항목:**
- 누적 수익률이 양수인가
- MDD 한도 이내인가
- 시스템 안정성에 문제가 없었는가
- AI 판단의 정확도가 유지되는가

---

## 10. 핵심 원칙 요약

1. **잃지 않는 것이 첫 번째**: 수익보다 자본 보존이 우선
2. **AI를 신뢰하되 검증하라**: LLM의 판단은 항상 리스크 관리 계층을 통과해야 함
3. **점진적으로 진행하라**: 모의투자 → 소액 → 점진적 증액
4. **모든 것을 기록하라**: 판단 근거, 거래 내역, 실패 원인 전부 기록
5. **최악의 상황을 가정하라**: Kill Switch, 장애 대응, 비상 연락망 항시 준비
