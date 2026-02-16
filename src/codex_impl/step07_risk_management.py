from __future__ import annotations

from dataclasses import dataclass

from .models import RiskCheckResult, Signal


@dataclass
class KillSwitch:
    active: bool = False
    reason: str = ""

    def activate(self, reason: str) -> None:
        self.active = True
        self.reason = reason

    def deactivate(self) -> None:
        self.active = False
        self.reason = ""


class RiskGate:
    """07-risk-management.md with hard+dynamic checks."""

    def __init__(self, settings: dict, kill_switch: KillSwitch | None = None) -> None:
        self.settings = settings
        self.kill_switch = kill_switch or KillSwitch()

    def _hard_limit_checks(self, signal: Signal, portfolio: dict) -> list[dict[str, str]]:
        checks: list[dict[str, str]] = []
        hard = self.settings["risk"]["hard_limits"]

        if portfolio.get("drawdown_pct", 0.0) <= hard["max_drawdown_pct"]:
            checks.append({"level": "1", "rule": "drawdown", "result": "BLOCKED"})
        else:
            checks.append({"level": "1", "rule": "drawdown", "result": "OK"})

        if portfolio.get("daily_pnl_pct", 0.0) <= hard["max_daily_loss_pct"]:
            checks.append({"level": "1", "rule": "daily_loss", "result": "BLOCKED"})
        else:
            checks.append({"level": "1", "rule": "daily_loss", "result": "OK"})

        max_positions = int(hard["max_total_positions"])
        if signal.decision == "BUY" and int(portfolio.get("open_positions", 0)) >= max_positions:
            checks.append({"level": "1", "rule": "max_positions", "result": "BLOCKED"})
        else:
            checks.append({"level": "1", "rule": "max_positions", "result": "OK"})

        return checks

    def _dynamic_checks(self, market_state: dict) -> list[dict[str, str]]:
        checks: list[dict[str, str]] = []
        if market_state.get("spread_pct", 0.0) > 0.005:
            checks.append({"level": "2", "rule": "spread", "result": "BLOCKED"})
        else:
            checks.append({"level": "2", "rule": "spread", "result": "OK"})

        if market_state.get("api_failures", 0) >= 5:
            checks.append({"level": "2", "rule": "api_failures", "result": "BLOCKED"})
        else:
            checks.append({"level": "2", "rule": "api_failures", "result": "OK"})

        return checks

    def check(self, signal: Signal, portfolio: dict, market_state: dict | None = None) -> RiskCheckResult:
        if self.kill_switch.active:
            return RiskCheckResult(False, 0, blocker=f"KILL_SWITCH:{self.kill_switch.reason}", checks=[])

        market_state = market_state or {}
        checks = self._hard_limit_checks(signal, portfolio) + self._dynamic_checks(market_state)

        blocked = next((c for c in checks if c["result"] == "BLOCKED"), None)
        if blocked:
            if blocked["rule"] in {"drawdown", "daily_loss", "api_failures"}:
                self.kill_switch.activate(reason=blocked["rule"])
            return RiskCheckResult(False, int(blocked["level"]), blocker=blocked["rule"], checks=checks)

        return RiskCheckResult(True, 3, blocker="ALL_PASSED", checks=checks)
