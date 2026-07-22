"""Small public-boundary scoreboards for deterministic integration tests."""

from __future__ import annotations

from collections import deque


class FrameScoreboard:
    """Compare observed frame bytes with independently produced expectations."""

    def __init__(self, expected: tuple[bytes, ...]) -> None:
        self._expected = deque(expected)

    def observe(self, frame: bytes) -> None:
        if not self._expected:
            raise AssertionError(f"unexpected frame: {frame.hex()}")
        expected = self._expected.popleft()
        if frame != expected:
            raise AssertionError(
                f"frame mismatch\nexpected={expected.hex()}\nobserved={frame.hex()}"
            )

    def assert_complete(self) -> None:
        if self._expected:
            raise AssertionError(f"{len(self._expected)} expected frame(s) were not observed")
