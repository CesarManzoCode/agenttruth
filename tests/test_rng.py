"""Counter-based BLAKE2b randomness (§5.1): replayable, independent streams, unbiased helpers."""

from __future__ import annotations

import hashlib

from hypothesis import given
from hypothesis import strategies as st

from agenttruth.dataset.rng import Stream


def test_u64_matches_the_contract_formula() -> None:
    stream = Stream("seed", "name")
    block = b"seed\x00name\x00" + (0).to_bytes(8, "big")
    assert stream.u64() == int.from_bytes(hashlib.blake2b(block, digest_size=8).digest(), "big")


def test_streams_replay_and_are_independent() -> None:
    a = [Stream("s", "x").u64() for _ in range(3)]
    b = [Stream("s", "x").u64() for _ in range(3)]
    assert a == b
    first = Stream("s", "x")
    other = Stream("s", "y")
    other.u64()
    assert first.u64() == Stream("s", "x").u64()


@given(st.integers(-1000, 1000), st.integers(0, 1000), st.text(max_size=20))
def test_randint_stays_in_range(low: int, span: int, name: str) -> None:
    stream = Stream("seed", name)
    assert all(low <= stream.randint(low, low + span) <= low + span for _ in range(20))


@given(st.text(max_size=10))
def test_random_and_poisson_ranges(name: str) -> None:
    stream = Stream("seed", name)
    assert all(0.0 <= stream.random() < 1.0 for _ in range(50))
    assert all(stream.poisson(1.5) >= 0 for _ in range(20))
    assert stream.weighted([("a", 1.0)]) == "a"
    assert len(stream.hex(21)) == 21
