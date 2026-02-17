"""Abstract base class for all trading algorithms.

Every concrete algorithm (Sentiment Momentum, Technical Trend, etc.)
inherits from ``BaseAlgorithm`` and implements the three abstract
members:

* ``name``             -- unique identifier string
* ``required_data()``  -- declares which data fields the algorithm needs
* ``generate_signal()`` -- produces a ``Signal`` from an ``AlgorithmContext``

This guarantees a uniform interface so that the ``AlgorithmRouter`` and
``EnsembleRunner`` can work with any algorithm interchangeably.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models.signal import AlgorithmContext, Signal


class BaseAlgorithm(ABC):
    """Base class that every analysis algorithm must extend.

    Parameters
    ----------
    config:
        Algorithm-specific configuration dict parsed from
        ``settings.yaml → algorithms.<name>``.
    """

    def __init__(self, config: dict) -> None:
        self.config = config

    @abstractmethod
    def generate_signal(self, ctx: AlgorithmContext) -> Signal:
        """Analyse the current market context and return a trading signal.

        Implementations must always return a valid ``Signal`` -- never
        raise on normal market conditions.  Unexpected errors should
        be caught and surfaced as a ``HOLD`` signal with a descriptive
        ``reason_codes`` entry.
        """
        ...

    @abstractmethod
    def required_data(self) -> list[str]:
        """Declare which ``AlgorithmContext`` fields are needed.

        The router uses this list to optimise data fetching so that
        only the required sources are queried.

        Example return values: ``["price_bars"]``,
        ``["news_events", "sentiment_current", "sentiment_previous"]``.
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique algorithm identifier (e.g. ``"sentiment_momentum"``)."""
        ...
