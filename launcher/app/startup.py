"""Startup timing, so slow starts can be blamed on a stage.

Stages wrap the work in ``AppContext.create`` and ``main``; the report is
a list of ``(name, milliseconds)`` pairs, longest first. Recording costs
nothing measurable and only runs in-process.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field


@dataclass
class StartupProfiler:
    """Collects named stage durations for one startup."""

    _starts: dict[str, float] = field(default_factory=dict, repr=False)
    stages: list[tuple[str, float]] = field(default_factory=list)

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        """Time one named stage."""
        start = time.perf_counter()
        try:
            yield
        finally:
            self.stages.append((name, (time.perf_counter() - start) * 1000.0))

    def report(self, *, limit: int = 12) -> list[tuple[str, float]]:
        """Stages sorted longest first, for logging or About."""
        return sorted(self.stages, key=lambda item: item[1], reverse=True)[:limit]

    def total_ms(self) -> float:
        return sum(milliseconds for _, milliseconds in self.stages)
