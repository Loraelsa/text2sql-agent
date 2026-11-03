from text2sql import ScriptedLLM, Text2SQLAgent, extract_sql
from text2sql.schema import load_schema, prune_schema


def test_extract_sql_from_fence():
    assert extract_sql("Sure!\n```sql\nSELECT 1\n```\nDone") == "SELECT 1"


def test_extract_sql_without_fence():
    assert extract_sql("Here you go: SELECT 2") == "SELECT 2"


def test_success_first_try(db):
    llm = ScriptedLLM(["```sql\nSELECT COUNT(*) FROM customers\n```"])
    res = Text2SQLAgent(db, llm).ask("How many customers are there?")
    assert res.success and res.rows == [(40,)] and len(res.attempts) == 1


def test_self_correction_recovers_from_sql_error(db):
    llm = ScriptedLLM([
        "```sql\nSELECT COUNT(*) FROM customer\n```",   # wrong table name
        "```sql\nSELECT COUNT(*) FROM customers\n```",
    ])
    res = Text2SQLAgent(db, llm).ask("How many customers are there?")
    assert res.success and res.rows == [(40,)]
    assert len(res.attempts) == 2 and "no such table" in res.attempts[0].error
    # The error message was fed back to the model on the retry.
    assert "no such table" in llm.calls[1][1][-1]["content"]


def test_without_self_correction_a_single_failure_is_final(db):
    llm = ScriptedLLM(["SELECT COUNT(*) FROM customer", "SELECT COUNT(*) FROM customers"])
    res = Text2SQLAgent(db, llm, self_correct=False).ask("How many customers are there?")
    assert not res.success and len(res.attempts) == 1


def test_gives_up_after_max_retries(db):
    llm = ScriptedLLM(["SELECT * FROM nope"] * 10)
    res = Text2SQLAgent(db, llm, max_retries=2).ask("anything")
    assert not res.success and len(res.attempts) == 3 and res.error


def test_unsafe_query_is_blocked_and_retried(db):
    llm = ScriptedLLM(["DROP TABLE customers", "SELECT COUNT(*) FROM customers"])
    res = Text2SQLAgent(db, llm).ask("How many customers are there?")
    assert res.success and "Only SELECT" in res.attempts[0].error
    assert db.execute("SELECT COUNT(*) FROM customers").rows == [(40,)]


def test_explanation_failure_does_not_break_result(db):
    class Flaky(ScriptedLLM):
        def complete(self, system, messages):
            if "explain" in system.lower():
                raise RuntimeError("boom")
            return super().complete(system, messages)

    res = Text2SQLAgent(db, Flaky(["SELECT 1"])).ask("one?", explain=True)
    assert res.success and res.explanation is None


def test_pruning_keeps_relevant_and_join_tables(db):
    tables = load_schema(db)
    kept = {t.name for t in prune_schema("Which customers have reviewed a product?", tables, max_tables=3)}
    assert {"customers", "reviews", "products"} <= kept


def test_junction_tables_are_bridged_but_fact_tables_are_not(tmp_path):
    import sqlite3
    from text2sql import Database

    path = tmp_path / "uni.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE student (student_id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE course (course_id INTEGER PRIMARY KEY, title TEXT);
        CREATE TABLE enrollment (student_id INTEGER REFERENCES student(student_id),
                                 course_id INTEGER REFERENCES course(course_id));
        CREATE TABLE grade (grade_id INTEGER PRIMARY KEY, student_id INTEGER REFERENCES student(student_id),
                            course_id INTEGER REFERENCES course(course_id), score REAL);
        CREATE TABLE room (room_id INTEGER PRIMARY KEY, building TEXT);
        CREATE TABLE misc (misc_id INTEGER PRIMARY KEY, note TEXT);
    """)
    conn.commit(); conn.close()
    tables = load_schema(Database(path))
    kept = {t.name for t in prune_schema("Which student takes which course title?", tables, max_tables=2)}
    assert {"student", "course", "enrollment"} <= kept
    assert "grade" not in kept and "room" not in kept


def test_pruning_falls_back_to_full_schema_when_nothing_matches(db):
    tables = load_schema(db)
    assert len(prune_schema("zzz qqq", tables, max_tables=2)) == len(tables)


def test_pruned_schema_is_smaller_and_retry_shows_full_schema(db):
    llm = ScriptedLLM(["SELECT * FROM nope", "SELECT COUNT(*) FROM orders"])
    agent = Text2SQLAgent(db, llm, max_tables=2)
    res = agent.ask("How many orders are there?")
    first_prompt = llm.calls[0][1][0]["content"]
    assert "TABLE reviews" not in first_prompt            # pruned out
    assert "TABLE reviews" in llm.calls[1][1][-1]["content"]  # restored on retry
    assert res.success
