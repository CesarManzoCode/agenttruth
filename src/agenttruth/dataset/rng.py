"""Counter-based BLAKE2b randomness (contract §5.1).

``u64 = int.from_bytes(blake2b(seed ‖ 0x00 ‖ stream ‖ 0x00 ‖ counter_be64, digest_size=8))``. Each
named stream is independent and replayable; nothing here reads the clock, ``random`` or ``numpy``.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence

__all__ = ["Stream"]

_TWO_53 = float(1 << 53)


class Stream:
    """A deterministic random stream identified by ``(seed, name)``.

    Draws consume one or more 64-bit counter blocks; two streams with different names never share
    blocks, so adding draws to one stream never shifts another (this is what keeps planted faults
    isolated when switched off).
    """

    __slots__ = ("_counter", "_prefix")

    def __init__(self, seed: str, name: str) -> None:
        self._prefix = seed.encode("utf-8") + b"\x00" + name.encode("utf-8") + b"\x00"
        self._counter = 0

    def u64(self) -> int:
        """Return the next 64-bit unsigned integer."""
        block = self._prefix + self._counter.to_bytes(8, "big")
        self._counter += 1
        return int.from_bytes(hashlib.blake2b(block, digest_size=8).digest(), "big")

    def random(self) -> float:
        """Return a float uniform in ``[0, 1)`` with 53 bits of precision."""
        return (self.u64() >> 11) / _TWO_53

    def randint(self, low: int, high: int) -> int:
        """Return an integer uniform in ``[low, high]`` (rejection sampling, no modulo bias).

        Raises ``ValueError`` if ``high < low``.
        """
        if high < low:
            raise ValueError(f"empty range [{low}, {high}]")
        span = high - low + 1
        limit = ((1 << 64) // span) * span
        while True:
            value = self.u64()
            if value < limit:
                return low + value % span

    def bernoulli(self, p: float) -> bool:
        """Return True with probability ``p``."""
        return self.random() < p

    def choice[T](self, items: Sequence[T]) -> T:
        """Return a uniformly chosen element. Raises ``ValueError`` on an empty sequence."""
        if not items:
            raise ValueError("choice from an empty sequence")
        return items[self.randint(0, len(items) - 1)]

    def weighted[T](self, items: Sequence[tuple[T, float]]) -> T:
        """Return an element chosen with probability proportional to its weight (weights > 0)."""
        total = math.fsum(weight for _, weight in items)
        if not items or total <= 0:
            raise ValueError("weighted choice needs positive total weight")
        target = self.random() * total
        cumulative = 0.0
        for item, weight in items:
            cumulative += weight
            if target < cumulative:
                return item
        return items[-1][0]

    def poisson(self, lam: float) -> int:
        """Return a Poisson(``lam``) draw (Knuth's method; intended for small ``lam``)."""
        if lam <= 0:
            return 0
        threshold = math.exp(-lam)
        count = 0
        product = self.random()
        while product > threshold:
            count += 1
            product *= self.random()
        return count

    def hex(self, digits: int) -> str:
        """Return ``digits`` lowercase hex characters."""
        out = ""
        while len(out) < digits:
            out += f"{self.u64():016x}"
        return out[:digits]
