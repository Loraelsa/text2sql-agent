"""Read-only SQL safety layer.

Three independent defences, so that a single bypass is not enough:

1. ``validate_read_only``  - lexical check: one statement, SELECT/WITH only,
   no write/DDL/PRAGMA keywords (string literals and comments are ignored).
2. ``read_only_authorizer`` - SQLite authorizer callback that denies every
   action except reads, so even a query that slips past (1) cannot write.
3. The database is opened with ``mode=ro`` (see ``db.py``).
"""

from __future__ import annotations

import re
import sqlite3


class UnsafeSQLError(ValueError):
    """Raised when a query is not a single read-only SELECT."""


# Quoted strings/identifiers are matched first so that a `--` inside a string is
# not mistaken for a comment (and vice versa). Comments become a space.
_TOKEN_RE = re.compile(
    r"""('(?:[^']|'')*'|"(?:[^"]|"")*"|`[^`]*`|\[[^\]]*\])|(--[^\n]*|/\*.*?\*/)""",
    re.S,
)

_FORBIDDEN_RE = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|attach|detach|pragma|"
    r"vacuum|reindex|begin|commit|rollback|savepoint|release|load_extension)\b",
    re.I,
)

# sqlite3 action codes: SELECT=21, READ=20, FUNCTION=31, RECURSIVE=33
_ALLOWED_ACTIONS = frozenset({21, 20, 31, 33})


def mask_sql(sql: str) -> str:
    """Replace string literals/quoted identifiers with ``''`` and comments with a space."""
    return _TOKEN_RE.sub(lambda m: "''" if m.group(1) else " ", sql)


def validate_read_only(sql: str) -> str:
    """Return the query if it is a single read-only statement, else raise."""
    if not sql or not sql.strip():
        raise UnsafeSQLError("Empty query.")

    body = mask_sql(sql).strip().rstrip(";").strip()
    if not body:
        raise UnsafeSQLError("Empty query.")
    if ";" in body:
        raise UnsafeSQLError("Only a single SQL statement is allowed.")
    if not re.match(r"(select|with)\b", body, re.I):
        raise UnsafeSQLError("Only SELECT queries (optionally starting with WITH) are allowed.")
    match = _FORBIDDEN_RE.search(body)
    if match:
        raise UnsafeSQLError(f"Forbidden keyword in query: {match.group(1).upper()}.")
    return sql.strip()


def read_only_authorizer(action, arg1, arg2, db_name, source):  # noqa: ANN001
    """SQLite authorizer: allow reads, deny everything else."""
    return sqlite3.SQLITE_OK if action in _ALLOWED_ACTIONS else sqlite3.SQLITE_DENY
