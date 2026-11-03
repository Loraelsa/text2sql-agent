#!/usr/bin/env python
"""Benchmark the agent by execution accuracy: does the predicted query return the same rows as the gold query?

Examples
--------
  # Harness self-check, no API key needed (the "model" replays the gold SQL, so expect 100%):
  python benchmark/run_benchmark.py --oracle

  # Real run on the bundled sample database:
  python benchmark/run_benchmark.py --provider anthropic

  # Real run on a Spider subset (download Spider yourself, see README):
  python benchmark/run_benchmark.py --spider-dir data/spider --limit 100
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from text2sql.agent import Text2SQLAgent  # noqa: E402
from text2sql.db import Database, SQLExecutionError  # noqa: E402
from text2sql.evaluation import has_order_by, results_match  # noqa: E402
from text2sql.guard import UnsafeSQLError  # noqa: E402
from text2sql.llm import ScriptedLLM, get_llm  # noqa: E402
from text2sql.sample_db import DEFAULT_PATH, ensure_sample_db  # noqa: E402

MODES = {
    "baseline": dict(prune=False, self_correct=False),        # one shot, full schema
    "self_correct": dict(prune=False, self_correct=True),     # + retry on SQL errors
    "full": dict(prune=True, self_correct=True),              # + schema pruning
}


@dataclass
class Case:
    id: str
    db_path: Path
    question: str
    gold_sql: str
    difficulty: str = "n/a"


def load_cases(args) -> list[Case]:
    if args.spider_dir:
        root = Path(args.spider_dir)
        dev = json.loads((root / "dev.json").read_text(encoding="utf-8"))
        cases = [
            Case(f"spider-{i}", root / "database" / d["db_id"] / f"{d['db_id']}.sqlite", d["question"], d["query"])
            for i, d in enumerate(dev)
        ]
    else:
        db_path = ensure_sample_db(args.db)
        raw = json.loads(Path(args.questions).read_text(encoding="utf-8"))
        cases = [Case(r["id"], db_path, r["question"], r["gold_sql"], r.get("difficulty", "n/a")) for r in raw]
    return cases[: args.limit] if args.limit else cases


def run_case(case: Case, mode: str, args) -> dict:
    row = {"id": case.id, "mode": mode, "difficulty": case.difficulty, "question": case.question,
           "gold_sql": case.gold_sql, "correct": False, "success": False, "attempts": 0,
           "pred_sql": "", "error": None, "latency_s": 0.0, "skipped": False}
    db = Database(case.db_path)
    try:
        gold = db.execute(case.gold_sql)
    except (UnsafeSQLError, SQLExecutionError) as exc:
        row.update(skipped=True, error=f"gold query failed: {exc}")
        return row

    llm = ScriptedLLM([case.gold_sql] * 8) if args.oracle else get_llm(args.provider, args.model)
    agent = Text2SQLAgent(db, llm, max_retries=args.retries, **MODES[mode])
    try:
        res = agent.ask(case.question)
    except Exception as exc:  # noqa: BLE001 - API failure for one case should not kill the run
        row["error"] = f"agent error: {exc}"
        return row
    row.update(success=res.success, attempts=len(res.attempts), pred_sql=res.sql,
               error=res.error, latency_s=round(res.latency_s, 2))
    if res.success:
        row["correct"] = results_match(res.rows, gold.rows, ordered=has_order_by(case.gold_sql))
    return row


def pct(n: int, d: int) -> str:
    return f"{100 * n / d:.1f}%" if d else "n/a"


def summarize(rows: list[dict], modes: list[str]) -> str:
    lines = ["| Mode | Accuracy | Valid SQL | Avg attempts | Avg latency (s) |", "|---|---|---|---|---|"]
    by_diff = ["", "| Mode | " + " | ".join(sorted({r['difficulty'] for r in rows})) + " |"]
    by_diff.append("|---|" + "---|" * len({r["difficulty"] for r in rows}))
    for mode in modes:
        rs = [r for r in rows if r["mode"] == mode and not r["skipped"]]
        n = len(rs)
        lines.append(
            f"| {mode} | {pct(sum(r['correct'] for r in rs), n)} ({sum(r['correct'] for r in rs)}/{n}) "
            f"| {pct(sum(r['success'] for r in rs), n)} "
            f"| {sum(r['attempts'] for r in rs) / n:.2f} | {sum(r['latency_s'] for r in rs) / n:.2f} |"
            if n else f"| {mode} | n/a | n/a | n/a | n/a |"
        )
        groups = defaultdict(list)
        for r in rs:
            groups[r["difficulty"]].append(r["correct"])
        by_diff.append(f"| {mode} | " + " | ".join(
            pct(sum(groups[d]), len(groups[d])) for d in sorted({x['difficulty'] for x in rows})) + " |")
    return "\n".join(lines + by_diff)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--questions", default=str(ROOT / "benchmark" / "shop_questions.json"))
    p.add_argument("--db", default=str(ROOT / DEFAULT_PATH))
    p.add_argument("--spider-dir", help="Path to an extracted Spider dataset (contains dev.json and database/)")
    p.add_argument("--modes", default="baseline,self_correct,full", help="Comma-separated subset of: " + ",".join(MODES))
    p.add_argument("--limit", type=int, help="Only run the first N questions")
    p.add_argument("--provider")
    p.add_argument("--model")
    p.add_argument("--retries", type=int, default=3)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--oracle", action="store_true", help="Replay gold SQL instead of calling an LLM (harness self-check)")
    p.add_argument("--out", default=str(ROOT / "benchmark" / "results"))
    args = p.parse_args()

    modes = [m.strip() for m in args.modes.split(",")]
    unknown = [m for m in modes if m not in MODES]
    if unknown:
        p.error(f"unknown mode(s): {', '.join(unknown)}")

    cases = load_cases(args)
    print(f"Running {len(cases)} questions x {len(modes)} modes ({'oracle' if args.oracle else args.provider or 'default provider'})")
    jobs = [(c, m) for m in modes for c in cases]
    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=1 if args.oracle else args.workers) as pool:
        rows = list(pool.map(lambda j: run_case(j[0], j[1], args), jobs))

    summary = summarize(rows, modes)
    print("\n" + summary)
    skipped = sum(r["skipped"] for r in rows)
    if skipped:
        print(f"\n{skipped} case(s) skipped because the gold query failed to run.")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    (out / "results.md").write_text(
        f"# Benchmark results\n\n{len(cases)} questions, {'oracle self-check' if args.oracle else args.provider or 'default provider'}, "
        f"model: {args.model or 'default'}, {time.strftime('%Y-%m-%d')}\n\n{summary}\n", encoding="utf-8")
    print(f"\nWrote {out / 'results.json'} and {out / 'results.md'} in {time.monotonic() - start:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
