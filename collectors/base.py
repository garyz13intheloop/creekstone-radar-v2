"""
Base collector interface. All collectors inherit from this.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone

from models.item import SignalItem

log = logging.getLogger(__name__)


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class BaseCollector(ABC):
    source_id: str = "base"

    def collect(self) -> list[SignalItem]:
        try:
            items = self._collect()
            log.info("[%s] collected %d items", self.source_id, len(items))
            return items
        except Exception as e:
            log.error("[%s] collection failed: %s", self.source_id, e, exc_info=True)
            return []

    @abstractmethod
    def _collect(self) -> list[SignalItem]:
        ...
