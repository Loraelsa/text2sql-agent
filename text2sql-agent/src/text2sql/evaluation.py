"""Execution-accuracy comparison between a predicted and a gold query result."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Iterable

from .guard import mask_sql


def normalize_value(value: Any) -> Any:
    """Numbers compare equal across int/float (rounded to 2 dp); text is stripped."""
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value).strip()


def normalize_rows(rows: Iterable[Iterable[Any]]) -> list[tuple[Any, ...]]:
    return [tuple(normalize_value(v) for v in row) for row in rows]


def has_order_by(sql: str) -> bool:
    return re.search(r"\border\s+by\b", mask_sql(sql), re.I) is not None


def results_match(pred_rows, gold_rows, ordered: bool = False) -> bool:
    """True if both result sets are equal.

    Row order only matters when ``ordered`` (i.e. the gold query has ORDER BY).
    Column order always matters, and column names are ignored.
    """
    pred, gold = normalize_rows(pred_rows), normalize_rows(gold_rows)
    if ordered:
        return pred == gold
    return Counter(pred) == Counter(gold)
