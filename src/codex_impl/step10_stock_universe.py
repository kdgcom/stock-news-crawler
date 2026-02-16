from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class UniverseEntry:
    symbol: str
    market: str
    tier: int = 1
    sector: str = "unknown"
    enabled: bool = True


@dataclass
class UniverseManager:
    """10-stock-universe.md simplified tiered universe."""

    entries: dict[tuple[str, str], UniverseEntry] = field(default_factory=dict)

    def upsert(self, entry: UniverseEntry) -> None:
        self.entries[(entry.market, entry.symbol)] = entry

    def active_symbols(self, market: str | None = None) -> list[UniverseEntry]:
        values = [e for e in self.entries.values() if e.enabled]
        if market:
            values = [e for e in values if e.market == market]
        return sorted(values, key=lambda x: (x.tier, x.symbol))

    def demote_if_inactive(self, symbol: str, market: str, signal_count_30d: int) -> None:
        key = (market, symbol)
        row = self.entries.get(key)
        if not row:
            return
        if signal_count_30d == 0 and row.tier < 3:
            row.tier += 1

    def promote_if_liquid(self, symbol: str, market: str, avg_volume_20d: float, cutoff: float) -> None:
        key = (market, symbol)
        row = self.entries.get(key)
        if not row:
            return
        if avg_volume_20d >= cutoff and row.tier > 1:
            row.tier -= 1
