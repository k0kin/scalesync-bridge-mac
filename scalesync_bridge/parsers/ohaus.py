from __future__ import annotations
import re
from scalesync_bridge.parsers.base import BaseParser
from scalesync_bridge.models import WeightReading

# Stateless parser: each line is self-contained (confirmed by capture — scale emits
# one line per tick; no multi-line packets observed in counting mode).


class OhausParser(BaseParser):
    """Parse OHAUS ASCII serial output.

    Counting mode (confirmed format):
        '3   PCS'     — stable count
        '3   PCS ?'   — unstable/in-motion count

    Weighing mode (comma format):
        'ST,GS,  125.43,g'   — stable gram weight
        'US,GS,  125.43,g'   — unstable gram weight
        'ST,N,     3,PCS'    — stable piece count (comma variant)

    Simple (non-comma) gram format:
        '  +  125.43 lb'
        '     0.0000    lb'
    """

    _PCS_RE = re.compile(r'^(\d+)\s+PCS(\s+\?)?$', re.IGNORECASE)

    STABLE_PREFIX = "ST"
    UNSTABLE_PREFIX = "US"

    def request_weight(self) -> bytes:
        return b"P\r\n"

    def request_continuous(self) -> bytes:
        return b"CP\r\n"

    def request_tare(self) -> bytes:
        return b"T\r\n"

    def request_zero(self) -> bytes:
        return b"Z\r\n"

    def parse(self, line: str) -> WeightReading | None:
        line = line.strip()
        if not line:
            return None

        # Counting mode: "3   PCS" or "3   PCS ?" (confirmed protocol format)
        m = self._PCS_RE.match(line)
        if m:
            count = int(m.group(1))
            stable = m.group(2) is None  # presence of " ?" means unstable
            return WeightReading(stable=stable, unit="PCS", piece_count=count)

        # Comma format: "ST,GS,  125.43,g" or "ST,N,  3,PCS"
        if "," in line:
            parts = line.split(",")
            if len(parts) < 4:
                return None
            try:
                stable = parts[0].strip() == self.STABLE_PREFIX
                raw_unit = parts[3].strip()
                if raw_unit.upper() == "PCS":
                    count = int(float(parts[2].strip()))
                    return WeightReading(stable=stable, unit="PCS", piece_count=count)
                weight = float(parts[2].strip())
                return WeightReading(stable=stable, weight_g=weight, unit=raw_unit)
            except (ValueError, IndexError):
                return None

        # Simple gram/lb format: "  +  125.43 lb" or "     0.0000    lb"
        match = re.match(r'[+\-\s]*([\d.]+)\s+(\w+)', line)
        if not match:
            return None
        try:
            weight = float(match.group(1))
            unit = match.group(2)
            return WeightReading(stable=True, weight_g=weight, unit=unit)
        except ValueError:
            return None
