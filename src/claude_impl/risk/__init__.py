"""Risk management package -- 3-layer risk gate for the stock trading system.

Layers
------
1. **Hard Limits** (:class:`HardLimitChecker`) -- absolute, unconditional
   safety boundaries that can never be overridden.
2. **Dynamic Risk** (:class:`DynamicRiskChecker`) -- market-condition-aware
   checks that adjust position sizing and impose cooldowns.
3. **Kill Switch** (:class:`KillSwitch`) -- emergency halt that blocks all
   trading until manually deactivated.

Additionally, :class:`StopLossChecker` evaluates individual positions
against fixed, trailing, and time-based stop-loss rules.

:class:`RiskGate` is the unified entry point that orchestrates all layers.
"""

from claude_impl.risk.dynamic_risk import DynamicRiskChecker
from claude_impl.risk.hard_limits import HardLimitChecker
from claude_impl.risk.kill_switch import KillSwitch
from claude_impl.risk.risk_gate import RiskGate
from claude_impl.risk.stop_loss import StopLossChecker

__all__ = [
    "DynamicRiskChecker",
    "HardLimitChecker",
    "KillSwitch",
    "RiskGate",
    "StopLossChecker",
]
