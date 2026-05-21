from __future__ import annotations
from abc import ABC, abstractmethod
from scalesync_bridge.models import WeightReading


class BaseParser(ABC):
    @abstractmethod
    def parse(self, line: str) -> WeightReading | None:
        """Parse a line of serial output into a WeightReading."""
        ...

    @abstractmethod
    def request_weight(self) -> bytes:
        """Command to request a weight reading."""
        ...

    @abstractmethod
    def request_tare(self) -> bytes:
        """Command to tare the scale."""
        ...

    @abstractmethod
    def request_zero(self) -> bytes:
        """Command to zero the scale."""
        ...

    def request_continuous(self) -> bytes:
        """Command to start continuous output. Override if supported."""
        return self.request_weight()
