"""stats_helpers.py — Pure-Python statistical utilities."""
from __future__ import annotations

import math


def pearson(xs: list[float], ys: list[float]) -> float | None:
    """Compute Pearson correlation coefficient between two sequences.

    Returns None if there are fewer than 2 overlapping points, or if
    either sequence has zero variance (would cause division by zero).
    """
    n = min(len(xs), len(ys))
    if n < 2:
        return None

    xs = xs[:n]
    ys = ys[:n]

    mean_x = sum(xs) / n
    mean_y = sum(ys) / n

    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)

    denom = math.sqrt(var_x * var_y)
    if denom == 0.0:
        return None

    return cov / denom


def safe_div(a: float, b: float, default: float = 0.0) -> float:
    """Divide a by b, returning default if b is zero."""
    if b == 0:
        return default
    return a / b
