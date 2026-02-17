"""Abstract broker interface and Phase 3 stubs.

Defines :class:`BaseBroker` -- the common contract that all broker adapters
must satisfy -- together with stub implementations for Korean Investment
Securities (:class:`KISBroker`) and Alpaca (:class:`AlpacaBroker`).

Phase 3 will replace the stub methods with real API calls once paper-trading
has been validated for at least four consecutive weeks.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseBroker(ABC):
    """Abstract base class for all broker adapters.

    Every broker implementation must support placing/cancelling orders and
    querying positions and account balance.
    """

    @abstractmethod
    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: int,
        order_type: str = "market",
    ) -> dict:
        """Submit a new order to the broker.

        Parameters
        ----------
        symbol:
            Ticker or stock code (e.g. ``"005930"``, ``"AAPL"``).
        side:
            ``"BUY"`` or ``"SELL"``.
        quantity:
            Number of shares.
        order_type:
            ``"market"`` (default), ``"limit"``, etc.

        Returns
        -------
        dict
            Broker-specific order acknowledgement containing at minimum
            ``{"order_id": str, "status": str}``.
        """
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> dict:
        """Cancel an outstanding order.

        Parameters
        ----------
        order_id:
            Broker-assigned order identifier.

        Returns
        -------
        dict
            Cancellation result with ``{"order_id": str, "status": str}``.
        """
        ...

    @abstractmethod
    def get_positions(self) -> list[dict]:
        """Return all current open positions.

        Each position dict should contain at least ``symbol``, ``quantity``,
        ``avg_cost``, and ``current_price``.
        """
        ...

    @abstractmethod
    def get_balance(self) -> dict:
        """Return the current account balance.

        Should include at minimum ``{"total_equity": float,
        "buying_power": float, "cash": float}``.
        """
        ...

    def cancel_all_orders(self) -> list[dict]:
        """Cancel every outstanding order.

        The default implementation is a no-op; subclasses should override
        this with a bulk-cancel API call where available.

        Returns
        -------
        list[dict]
            A list of cancellation results, one per cancelled order.
        """
        return []


# ---------------------------------------------------------------------------
# Phase 3 stubs
# ---------------------------------------------------------------------------

class KISBroker(BaseBroker):
    """Korean Investment Securities (KIS) API broker adapter.

    .. note::
        This is a Phase 3 stub.  All methods raise
        :class:`NotImplementedError` until the KIS OpenAPI integration
        is completed.

    Configuration keys (future)::

        broker.kr.app_key       -- KIS application key
        broker.kr.app_secret    -- KIS application secret
        broker.kr.account_no    -- securities account number
        broker.kr.is_paper      -- use the mock-trading endpoint
    """

    def __init__(self, config: dict | None = None) -> None:
        self._config = config or {}

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: int,
        order_type: str = "market",
    ) -> dict:
        raise NotImplementedError(
            "KISBroker.place_order is a Phase 3 feature. "
            "Use PaperExecutor for Phase 1-2 paper trading."
        )

    def cancel_order(self, order_id: str) -> dict:
        raise NotImplementedError(
            "KISBroker.cancel_order is a Phase 3 feature. "
            "Use PaperExecutor for Phase 1-2 paper trading."
        )

    def get_positions(self) -> list[dict]:
        raise NotImplementedError(
            "KISBroker.get_positions is a Phase 3 feature. "
            "Use PositionManager for Phase 1-2 position tracking."
        )

    def get_balance(self) -> dict:
        raise NotImplementedError(
            "KISBroker.get_balance is a Phase 3 feature."
        )

    def cancel_all_orders(self) -> list[dict]:
        raise NotImplementedError(
            "KISBroker.cancel_all_orders is a Phase 3 feature."
        )


class AlpacaBroker(BaseBroker):
    """Alpaca API broker adapter for US equities.

    .. note::
        This is a Phase 3 stub.  All methods raise
        :class:`NotImplementedError` until the Alpaca integration is
        completed.

    Configuration keys (future)::

        broker.us.api_key       -- Alpaca API key
        broker.us.api_secret    -- Alpaca API secret
        broker.us.base_url      -- Alpaca API base URL
        broker.us.is_paper      -- use the paper-trading endpoint
    """

    def __init__(self, config: dict | None = None) -> None:
        self._config = config or {}

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: int,
        order_type: str = "market",
    ) -> dict:
        raise NotImplementedError(
            "AlpacaBroker.place_order is a Phase 3 feature. "
            "Use PaperExecutor for Phase 1-2 paper trading."
        )

    def cancel_order(self, order_id: str) -> dict:
        raise NotImplementedError(
            "AlpacaBroker.cancel_order is a Phase 3 feature. "
            "Use PaperExecutor for Phase 1-2 paper trading."
        )

    def get_positions(self) -> list[dict]:
        raise NotImplementedError(
            "AlpacaBroker.get_positions is a Phase 3 feature. "
            "Use PositionManager for Phase 1-2 position tracking."
        )

    def get_balance(self) -> dict:
        raise NotImplementedError(
            "AlpacaBroker.get_balance is a Phase 3 feature."
        )

    def cancel_all_orders(self) -> list[dict]:
        raise NotImplementedError(
            "AlpacaBroker.cancel_all_orders is a Phase 3 feature."
        )
