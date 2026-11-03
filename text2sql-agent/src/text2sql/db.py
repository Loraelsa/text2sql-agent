"""Safe, read-only SQLite access."""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from .guard import read_only_authorizer, validate_read_only


class SQLExecutionError(RuntimeError):
    """The database rejected or failed to run the query."""


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple[Any, ...]]
    truncated: bool = False
    elapsed_s: float = field(default=0.0)


class Database:
    """A SQLite file that can only be queried through the read-only guard."""

    def __init__(self, path: str | Path, max_rows: int = 200, timeout_s: float = 10.0):
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(f"Database not found: {self.path}")
        self.max_rows = max_rows
        self.timeout_s = timeout_s

    def _connect(self) -> sqlite3.Connection:
        uri = self.path.resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=self.timeout_s)
        # Some benchmark databases (e.g. Spider) contain non-UTF-8 bytes.
        conn.text_factory = lambda b: b.decode("utf-8", errors="replace")
        return conn

    @contextmanager
    def introspect(self) -> Iterator[sqlite3.Connection]:
        """Read-only connection WITHOUT the authorizer, for schema inspection only."""
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    def execute(self, sql: str) -> QueryResult:
        """Validate and run ``sql``. Raises UnsafeSQLError or SQLExecutionError."""
        cleaned = validate_read_only(sql)
        conn = self._connect()
        deadline = time.monotonic() + self.timeout_s
        try:
            conn.set_authorizer(read_only_authorizer)
            # Abort runaway queries (e.g. accidental cross joins).
            conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
            start = time.monotonic()
            cur = conn.execute(cleaned)
            columns = [d[0] for d in cur.description] if cur.description else []
            fetched = cur.fetchmany(self.max_rows + 1)
            truncated = len(fetched) > self.max_rows
            rows = [tuple(r) for r in fetched[: self.max_rows]]
            return QueryResult(columns, rows, truncated, time.monotonic() - start)
        except sqlite3.Error as exc:
            msg = str(exc)
            if "interrupted" in msg.lower():
                msg = f"Query timed out after {self.timeout_s:.0f}s."
            raise SQLExecutionError(msg) from exc
        finally:
            conn.close()
