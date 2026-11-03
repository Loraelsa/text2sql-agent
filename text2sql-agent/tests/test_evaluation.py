import json
from pathlib import Path

from text2sql.evaluation import has_order_by, results_match

QUESTIONS = json.loads((Path(__file__).parents[1] / "benchmark" / "shop_questions.json").read_text())


def test_row_order_ignored_without_order_by():
    assert results_match([(1,), (2,)], [(2,), (1,)])


def test_row_order_matters_with_order_by():
    assert not results_match([(1,), (2,)], [(2,), (1,)], ordered=True)


def test_duplicates_matter():
    assert not results_match([(1,), (1,)], [(1,)])


def test_numeric_tolerance_and_int_float():
    assert results_match([(3,)], [(3.0,)])
    assert results_match([(1.0000001,)], [(1.0,)])
    assert not results_match([(1.5,)], [(1.0,)])


def test_has_order_by_ignores_strings_and_comments():
    assert has_order_by("SELECT a FROM t ORDER BY a")
    assert not has_order_by("SELECT 'order by' FROM t")
    assert not has_order_by("SELECT a FROM t -- order by a")


def test_every_gold_query_runs_and_ids_are_unique(db):
    assert len({q["id"] for q in QUESTIONS}) == len(QUESTIONS) >= 25
    for q in QUESTIONS:
        res = db.execute(q["gold_sql"])
        assert res.rows, f"{q['id']} returns no rows, which makes it a weak test"


def test_oracle_self_check_scores_100_percent(db):
    from text2sql import ScriptedLLM, Text2SQLAgent

    for q in QUESTIONS:
        agent = Text2SQLAgent(db, ScriptedLLM([q["gold_sql"]]))
        res = agent.ask(q["question"])
        gold = db.execute(q["gold_sql"])
        assert res.success and results_match(res.rows, gold.rows, ordered=has_order_by(q["gold_sql"])), q["id"]
