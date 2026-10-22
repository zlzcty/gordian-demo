"""Wall-clock budget accounting shared by all stages."""
from __future__ import annotations

import time


class Budget:
    def __init__(self, total_s: float):
        self.total = float(total_s)
        self.start = time.time()

    @property
    def elapsed(self) -> float:
        return time.time() - self.start

    @property
    def remaining(self) -> float:
        return max(0.0, self.total - self.elapsed)

    def fraction(self, f: float, floor: float = 0.0) -> float:
        """A slice of the remaining time."""
        return max(floor, self.remaining * f)

    def exhausted(self, reserve_s: float = 0.0) -> bool:
        return self.remaining <= reserve_s

    def __repr__(self) -> str:
        return f"Budget(elapsed={self.elapsed:.0f}s remaining={self.remaining:.0f}s of {self.total:.0f}s)"
