from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from .models import SellRecommendation, Signal, TradeLedgerEntry
from .step07_risk_management import RiskGate
from .storage.step04_data_storage import InMemoryStorage


@dataclass
class ExecutionResult:
    status: str
    reason: str = ""
    fill_price: float | None = None


class PaperExecutor:
    """08-execution.md with holdings-only sell enforcement."""

    def __init__(self, storage: InMemoryStorage, risk_gate: RiskGate, auto_execute_sell: bool = False) -> None:
        self.storage = storage
        self.risk_gate = risk_gate
        self.auto_execute_sell = auto_execute_sell

    def execute_signal(
        self,
        signal: Signal,
        user_id: str,
        account_id: str,
        quantity: int,
        price: float,
        portfolio: dict,
        market_state: dict | None = None,
    ) -> ExecutionResult:
        risk = self.risk_gate.check(signal=signal, portfolio=portfolio, market_state=market_state)
        if not risk.passed:
            self.storage.append_decision_log(
                {
                    "decision_id": str(uuid4()),
                    "ts_utc": datetime.utcnow().isoformat(),
                    "symbol": signal.symbol,
                    "market": signal.market,
                    "decision": signal.decision,
                    "score": signal.score,
                    "risk_check": {
                        "passed": False,
                        "level": risk.level,
                        "blocker": risk.blocker,
                        "checks": risk.checks,
                    },
                    "final_action": "HOLD",
                    "reason_codes": ["RISK_BLOCKED", risk.blocker.upper()],
                }
            )
            return ExecutionResult(status="BLOCKED", reason=risk.blocker)

        if signal.decision == "SELL":
            holdings = self.storage.current_holdings(user_id=user_id, account_id=account_id)
            row = holdings.get(signal.symbol)
            if not row or row["net_quantity"] <= 0:
                return ExecutionResult(status="BLOCKED", reason="NO_OPEN_POSITION")
            if quantity > row["net_quantity"]:
                return ExecutionResult(status="BLOCKED", reason="SELL_QTY_EXCEEDS_HOLDINGS")

        if signal.decision == "HOLD":
            return ExecutionResult(status="SKIPPED", reason="HOLD_SIGNAL")

        side = "BUY" if signal.decision == "BUY" else "SELL"
        trade = TradeLedgerEntry(
            trade_id=str(uuid4()),
            user_id=user_id,
            account_id=account_id,
            symbol=signal.symbol,
            market=signal.market,
            side=side,
            quantity=quantity,
            price=price,
            source="paper_executor",
        )
        self.storage.append_trade(trade)
        return ExecutionResult(status="FILLED", fill_price=price)

    def generate_sell_recommendation(
        self,
        user_id: str,
        account_id: str,
        signal: Signal,
        min_confidence: float,
    ) -> SellRecommendation | None:
        holdings = self.storage.current_holdings(user_id=user_id, account_id=account_id)
        row = holdings.get(signal.symbol)
        if not row:
            return None
        if signal.decision not in {"SELL", "HOLD"}:
            return None
        if signal.confidence < min_confidence:
            return None

        action = "SELL" if signal.score <= -0.8 else "REDUCE" if signal.score <= -0.3 else "HOLD"
        rec = SellRecommendation(
            recommendation_id=str(uuid4()),
            user_id=user_id,
            account_id=account_id,
            symbol=signal.symbol,
            market=signal.market,
            action=action,
            score=signal.score,
            confidence=signal.confidence,
            target_reduce_pct=1.0 if action == "SELL" else 0.5 if action == "REDUCE" else 0.0,
            reason_codes=signal.reason_codes,
            evidence={"algorithm": signal.algorithm, "details": signal.details, "holding": row},
            requires_confirmation=not self.auto_execute_sell,
        )
        self.storage.append_recommendation(rec)
        return rec
