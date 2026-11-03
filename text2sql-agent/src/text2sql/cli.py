"""Command line interface: ``python -m text2sql "How many customers are there?"``."""

from __future__ import annotations

import argparse
import sys

from .agent import Text2SQLAgent
from .db import Database
from .llm import get_llm
from .sample_db import DEFAULT_PATH, ensure_sample_db


def _print_table(columns: list[str], rows: list[tuple]) -> None:
    cells = [[str(v) for v in r] for r in rows]
    widths = [max(len(c), *(len(r[i]) for r in cells)) if cells else len(c) for i, c in enumerate(columns)]
    print(" | ".join(c.ljust(w) for c, w in zip(columns, widths)))
    print("-+-".join("-" * w for w in widths))
    for r in cells:
        print(" | ".join(v.ljust(w) for v, w in zip(r, widths)))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="text2sql", description="Ask questions about a SQLite database in plain English.")
    p.add_argument("question", help="Question in natural language")
    p.add_argument("--db", default=str(DEFAULT_PATH), help="Path to a SQLite file (default: sample shop database)")
    p.add_argument("--provider", help="anthropic | openai | groq | gemini (default: $LLM_PROVIDER or anthropic)")
    p.add_argument("--model", help="Model name (default: $LLM_MODEL or the provider default)")
    p.add_argument("--no-prune", action="store_true", help="Send the full schema instead of a pruned one")
    p.add_argument("--no-self-correct", action="store_true", help="Single attempt, no retries on SQL errors")
    p.add_argument("--retries", type=int, default=3, help="Max self-correction retries (default 3)")
    p.add_argument("--explain", action="store_true", help="Add a plain-English explanation of the result")
    args = p.parse_args(argv)

    if args.db == str(DEFAULT_PATH):
        ensure_sample_db(DEFAULT_PATH)

    agent = Text2SQLAgent(
        Database(args.db), get_llm(args.provider, args.model),
        prune=not args.no_prune, self_correct=not args.no_self_correct, max_retries=args.retries,
    )
    res = agent.ask(args.question, explain=args.explain)

    print(f"Tables sent to the model: {', '.join(res.schema_tables)}")
    for i, attempt in enumerate(res.attempts, 1):
        status = "ok" if attempt.error is None else f"error: {attempt.error}"
        print(f"\nAttempt {i} ({status})\n{attempt.sql}")
    if not res.success:
        print("\nCould not produce a working query.", file=sys.stderr)
        return 1
    print()
    _print_table(res.columns, res.rows)
    if res.truncated:
        print("(results truncated)")
    if res.explanation:
        print(f"\n{res.explanation}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
