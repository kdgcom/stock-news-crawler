from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


DEFAULT_SETTINGS: dict[str, Any] = {
    "analysis": {
        "mode": "hybrid",
        "signal": {"buy_threshold": 0.6, "sell_threshold": -0.6},
        "hybrid": {
            "alpha_default": 0.7,
            "alpha_volatile": 0.5,
            "alpha_news_spike": 0.4,
            "agent_trigger": {
                "near_threshold_margin": 0.12,
                "conflict_required": True,
                "high_impact_event_types": ["earnings", "m_and_a", "regulation", "lawsuit"],
            },
            "fail_safe": {
                "timeout_ms": 2500,
                "on_agent_timeout": "numeric_only",
                "max_agent_calls_per_day": 5000,
            },
        },
    },
    "risk": {
        "hard_limits": {
            "max_daily_loss_pct": -0.03,
            "max_drawdown_pct": -0.15,
            "max_total_positions": 20,
            "max_single_stock_pct": 0.10,
        }
    },
    "trade_ledger": {
        "enabled": True,
        "record_buy": True,
        "record_sell": True,
        "holding_calculation": "fifo",
        "source_priority": ["broker_fill", "manual_input"],
    },
    "sell_recommendation": {
        "enabled": True,
        "holdings_only": True,
        "min_confidence": 0.6,
        "min_holding_quantity": 1,
        "block_if_no_open_position": True,
        "require_user_confirmation": True,
    },
    "portfolio_input": {
        "enabled": True,
        "provider": "cloud_functions",
        "refresh_required_hours": 24,
    },
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_merge(base[key], value)
        else:
            base[key] = value
    return base


@dataclass
class ConfigLoader:
    base_path: Path = Path("config/settings.yaml")
    local_path: Path = Path("config/settings.local.yaml")

    def load(self) -> dict[str, Any]:
        config = deepcopy(DEFAULT_SETTINGS)
        if yaml is None:
            return config
        if self.base_path.exists():
            deep_merge(config, yaml.safe_load(self.base_path.read_text(encoding="utf-8")) or {})
        if self.local_path.exists():
            deep_merge(config, yaml.safe_load(self.local_path.read_text(encoding="utf-8")) or {})
        return config
