"""The text-to-SQL agent: prune schema -> generate SQL -> execute -> self-correct on errors."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

from .db import Database, SQLExecutionError
from .guard import UnsafeSQLError
from .llm import LLM
from .schema import Table, format_schema, load_schema, prune_schema

SYSTEM_PROMPT = """You are an expert data analyst who writes SQLite queries.

Rules:
- Use ONLY the tables and columns shown in the schema.
- Write exactly one read-only SELECT query (CTEs are allowed). Never modify data.
- Reply with only the final query inside a ```sql fenced block, no commentary.
- Use SQLite syntax (strftime for dates, || for concatenation, LIMIT instead of TOP).
- Return only the columns the question asks for, in the order they are mentioned."""

EXPLAIN_PROMPT = (
    "You explain query results to a non-technical user in 1-3 plain sentences. "
    "Only state facts that appear in the result. Do not mention SQL."
)

_FENCE_RE = re.compile(r"```(?:sql|sqlite)?\s*\n?(.*?)```", re.S | re.I)
_START_RE = re.compile(r"\b(select|with)\b", re.I)


def extract_sql(text: str) -> str:
    """Pull the SQL out of an LLM reply (fenced block preferred, else first SELECT/WITH)."""
    match = _FENCE_RE.search(text)
    if match:
        return match.group(1).strip()
    start = _START_RE.search(text)
    return text[start.start():].strip() if start else text.strip()


@dataclass
class Attempt:
    sql: str
    error: str | None = None


@dataclass
class AgentResult:
    question: str
    success: bool
    sql: str = ""
    columns: list[str] = field(default_factory=list)
    rows: list[tuple[Any, ...]] = field(default_factory=list)
    truncated: bool = False
    error: str | None = None
    explanation: str | None = None
    attempts: list[Attempt] = field(default_factory=list)
    schema_tables: list[str] = field(default_factory=list)
    latency_s: float = 0.0


class Text2SQLAgent:
    def __init__(
        self,
        db: Database,
        llm: LLM,
        *,
        prune: bool = True,
        self_correct: bool = True,
        max_retries: int = 3,
        max_tables: int = 4,
    ):
        self.db = db
        self.llm = llm
        self.prune = prune
        self.self_correct = self_correct
        self.max_retries = max_retries
        self.max_tables = max_tables
        self._tables: list[Table] = load_schema(db)

    @property
    def tables(self) -> list[Table]:
        return self._tables

    def ask(self, question: str, explain: bool = False) -> AgentResult:
        start = time.monotonic()
        selected = prune_schema(question, self._tables, self.max_tables) if self.prune else self._tables
        was_pruned = len(selected) < len(self._tables)

        messages: list[dict] = [{
            "role": "user",
            "content": f"Database schema:\n\n{format_schema(selected)}\n\nQuestion: {question}\n\nWrite one SQLite query.",
        }]
        result = AgentResult(question=question, success=False, schema_tables=[t.name for t in selected])
        total_attempts = 1 + (self.max_retries if self.self_correct else 0)

        for i in range(total_attempts):
            raw = self.llm.complete(SYSTEM_PROMPT, messages)
            sql = extract_sql(raw)
            try:
                qr = self.db.execute(sql)
            except (UnsafeSQLError, SQLExecutionError) as exc:
                result.attempts.append(Attempt(sql, str(exc)))
                result.sql, result.error = sql, str(exc)
                feedback = (
                    f"That query failed with this error:\n{exc}\n\n"
                    "Fix the query and reply with only the corrected SQL in a ```sql block."
                )
                # If pruning may have dropped a needed table, show everything on the retry.
                if was_pruned and i == 0:
                    feedback += f"\n\nFull schema, in case a needed table was omitted:\n\n{format_schema(self._tables)}"
                messages += [{"role": "assistant", "content": raw}, {"role": "user", "content": feedback}]
                continue

            result.attempts.append(Attempt(sql))
            result.success, result.error = True, None
            result.sql, result.columns, result.rows, result.truncated = sql, qr.columns, qr.rows, qr.truncated
            break

        if result.success and explain:
            result.explanation = self._explain(question, result)
        result.latency_s = time.monotonic() - start
        return result

    def _explain(self, question: str, result: AgentResult) -> str | None:
        preview = "\n".join(str(r) for r in result.rows[:20]) or "(no rows)"
        prompt = f"Question: {question}\nColumns: {result.columns}\nRows:\n{preview}"
        try:
            return self.llm.complete(EXPLAIN_PROMPT, [{"role": "user", "content": prompt}]).strip()
        except Exception:  # noqa: BLE001 - the explanation is optional
            return None
