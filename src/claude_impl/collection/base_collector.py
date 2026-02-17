"""Base collector with retry logic and exponential backoff.

Implements the Template Method pattern: fetch -> normalize -> store.
All concrete collectors inherit from BaseCollector and implement
the three abstract methods.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    """Abstract base class for all data collectors.

    Provides a ``collect()`` template method that orchestrates the
    fetch -> normalize -> store pipeline with exponential-backoff retry.

    Subclasses must implement:
        * ``fetch()``      – retrieve raw data from the external source
        * ``normalize()``  – transform raw data into the standard schema
        * ``store()``      – persist normalised data to the target storage
    """

    MAX_RETRIES: int = 5
    BACKOFF_BASE: int = 2  # exponential backoff: 2, 4, 8, 16, 32 seconds

    # ------------------------------------------------------------------
    # Template method
    # ------------------------------------------------------------------

    def collect(self) -> list[dict[str, Any]]:
        """Execute the full collection pipeline with retry.

        Returns the normalised data list on success, or an empty list
        after all retries are exhausted.
        """

        last_exception: Exception | None = None

        for attempt in range(self.MAX_RETRIES):
            try:
                raw = self.fetch()
                normalised = self.normalize(raw)
                self.store(normalised)
                logger.info(
                    "%s: collected %d records successfully.",
                    self.__class__.__name__,
                    len(normalised),
                )
                return normalised
            except Exception as exc:
                last_exception = exc
                wait = self.BACKOFF_BASE ** (attempt + 1)
                logger.warning(
                    "%s: attempt %d/%d failed, retrying in %ds – %s",
                    self.__class__.__name__,
                    attempt + 1,
                    self.MAX_RETRIES,
                    wait,
                    exc,
                )
                time.sleep(wait)

        # All retries exhausted
        self.alert_failure(last_exception)
        return []

    # ------------------------------------------------------------------
    # Abstract hooks – must be implemented by every subclass
    # ------------------------------------------------------------------

    @abstractmethod
    def fetch(self) -> list[dict[str, Any]]:
        """Fetch raw data from the external source."""
        ...

    @abstractmethod
    def normalize(self, raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Transform raw records into the standard schema."""
        ...

    @abstractmethod
    def store(self, normalised: list[dict[str, Any]]) -> None:
        """Persist normalised records to the target storage."""
        ...

    # ------------------------------------------------------------------
    # Failure alerting
    # ------------------------------------------------------------------

    def alert_failure(self, last_exception: Exception | None = None) -> None:
        """Log a critical error after all retries are exhausted.

        Override in subclasses to add custom alerting (e.g. Telegram,
        Slack, PagerDuty).
        """
        logger.error(
            "%s: all %d retries exhausted. Last error: %s",
            self.__class__.__name__,
            self.MAX_RETRIES,
            last_exception,
        )
