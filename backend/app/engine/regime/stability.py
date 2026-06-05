"""Regime stability filter.

A regime must persist for `min_persistence` consecutive bars before the system
switches to it. Rapid flip-flopping (more than `flicker_threshold` changes within
the trailing `flicker_window`) is flagged as unstable (used to shrink sizing).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class StabilityFilter:
    min_persistence: int = 3
    flicker_window: int = 20
    flicker_threshold: int = 4

    def apply(self, labels: list[str]) -> tuple[list[str], list[bool]]:
        if not labels:
            return [], []

        stable: list[str] = []
        current = labels[0]
        candidate = labels[0]
        streak = 0
        for lab in labels:
            if lab == candidate:
                streak += 1
            else:
                candidate = lab
                streak = 1
            if candidate != current and streak >= self.min_persistence:
                current = candidate
            stable.append(current)

        flags: list[bool] = []
        for i in range(len(labels)):
            window = labels[max(0, i - self.flicker_window + 1) : i + 1]
            changes = sum(1 for a, b in zip(window, window[1:], strict=False) if a != b)
            flags.append(changes > self.flicker_threshold)
        return stable, flags
