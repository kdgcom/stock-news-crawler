from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SystemOverview:
    """00-overview.md mapped runtime profile."""

    markets: tuple[str, str] = ("KR", "US")
    primary_loop_minutes: int = 5
    default_posture: str = "no_new_position"
    priorities: tuple[str, str, str] = (
        "data_integrity",
        "risk_control",
        "profitability",
    )
    day_schedule_kst: dict[str, str] = field(
        default_factory=lambda: {
            "07:30": "KR pre-market briefing",
            "09:00": "KR session loop",
            "16:00": "KR daily close",
            "22:00": "US pre-market briefing",
            "23:30": "US session loop",
            "06:00": "US daily close",
        }
    )
