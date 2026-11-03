"""Schema introspection, relevance-based pruning and prompt formatting."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .db import Database


@dataclass
class Column:
    name: str
    type: str
    pk: bool = False


@dataclass
class ForeignKey:
    column: str
    ref_table: str
    ref_column: str


@dataclass
class Table:
    name: str
    columns: list[Column]
    foreign_keys: list[ForeignKey] = field(default_factory=list)
    sample_rows: list[tuple[Any, ...]] = field(default_factory=list)


def load_schema(db: Database, sample_rows: int = 2) -> list[Table]:
    """Read every user table with its columns, foreign keys and a few sample rows."""
    tables: list[Table] = []
    with db.introspect() as conn:
        names = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        for name in names:
            q = name.replace('"', '""')
            cols = [
                Column(r[1], r[2] or "", bool(r[5]))
                for r in conn.execute(f'PRAGMA table_info("{q}")')
            ]
            fks = [
                ForeignKey(r[3], r[2], r[4] or "")
                for r in conn.execute(f'PRAGMA foreign_key_list("{q}")')
            ]
            samples: list[tuple[Any, ...]] = []
            if sample_rows:
                try:
                    samples = [tuple(r) for r in conn.execute(f'SELECT * FROM "{q}" LIMIT {int(sample_rows)}')]
                except Exception:  # noqa: BLE001 - sampling is best effort
                    samples = []
            tables.append(Table(name, cols, fks, samples))
    return tables


# ----------------------------------------------------------------- pruning

_WORD_RE = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "of", "in", "to", "for", "and", "or", "is", "are", "was", "were", "by",
         "with", "per", "each", "all", "how", "many", "what", "which", "who", "show", "list", "name"}


def _stem(word: str) -> str:
    for suffix in ("ies", "es", "s"):
        if word.endswith(suffix) and len(word) > len(suffix) + 2:
            return word[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return word


def _tokens(text: str) -> set[str]:
    return {_stem(w) for w in _WORD_RE.findall(text.lower()) if w not in _STOP}


def score_table(question_tokens: set[str], table: Table) -> int:
    """Higher = more relevant. Table-name hits weigh more than column-name hits."""
    score = 0
    score += 3 * len(question_tokens & _tokens(table.name.replace("_", " ")))
    for col in table.columns:
        score += len(question_tokens & _tokens(col.name.replace("_", " ")))
    return score


def _is_junction(table: Table) -> bool:
    """A many-to-many link table: every column is a primary key or a foreign key."""
    fk_cols = {fk.column for fk in table.foreign_keys}
    return all(c.pk or c.name in fk_cols for c in table.columns)


def prune_schema(question: str, tables: list[Table], max_tables: int = 4) -> list[Table]:
    """Keep the tables most relevant to ``question`` plus the tables needed to join them.

    Falls back to the full schema when nothing matches, so pruning can reduce
    prompt size but never silently hides everything.
    """
    if len(tables) <= max_tables:
        return tables

    q_tokens = _tokens(question)
    scored = sorted(((score_table(q_tokens, t), t) for t in tables), key=lambda p: -p[0])
    chosen = [t for s, t in scored if s > 0][:max_tables]
    if not chosen:
        return tables

    by_name = {t.name: t for t in tables}
    selected = {t.name for t in chosen}
    # Pull in tables referenced by chosen tables (join targets) ...
    for t in chosen:
        for fk in t.foreign_keys:
            selected.add(fk.ref_table)
    # ... and pure junction tables (only keys, no payload) that link two or more selected tables.
    for t in tables:
        linked = {fk.ref_table for fk in t.foreign_keys} & selected
        if t.name not in selected and len(linked) >= 2 and _is_junction(t):
            selected.add(t.name)

    return [by_name[t.name] for t in tables if t.name in selected]


# -------------------------------------------------------------- formatting

def format_schema(tables: list[Table]) -> str:
    """Render the schema as compact DDL-like text for the prompt."""
    blocks: list[str] = []
    for t in tables:
        cols = ", ".join(
            f"{c.name} {c.type}".strip() + (" PRIMARY KEY" if c.pk else "") for c in t.columns
        )
        lines = [f"TABLE {t.name} ({cols})"]
        for fk in t.foreign_keys:
            lines.append(f"  FOREIGN KEY {t.name}.{fk.column} -> {fk.ref_table}.{fk.ref_column}")
        if t.sample_rows:
            lines.append("  sample rows:")
            for row in t.sample_rows:
                lines.append("    " + repr(tuple(row)))
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
