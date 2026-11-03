import pytest

from text2sql import SQLExecutionError, UnsafeSQLError, validate_read_only


@pytest.mark.parametrize("sql", [
    "SELECT 1",
    "select * from customers;",
    "WITH t AS (SELECT 1 AS x) SELECT x FROM t",
    "SELECT 'DROP TABLE x' AS s",                 # keyword inside a string literal
    "SELECT 1 -- DELETE FROM customers",           # keyword inside a comment
    "SELECT /* UPDATE */ 1",
    "SELECT 'a;b' AS s",                           # semicolon inside a string
])
def test_allows_read_only(sql):
    assert validate_read_only(sql)


@pytest.mark.parametrize("sql", [
    "",
    "   ",
    "DROP TABLE customers",
    "DELETE FROM customers",
    "INSERT INTO categories VALUES (9, 'x')",
    "UPDATE products SET price = 0",
    "SELECT 1; DROP TABLE customers",
    "PRAGMA table_info(customers)",
    "ATTACH DATABASE 'x.db' AS x",
    "CREATE TABLE t (a)",
    "WITH t AS (SELECT 1) DELETE FROM customers",
    "/* hi */ DROP TABLE customers",
])
def test_blocks_unsafe(sql):
    with pytest.raises(UnsafeSQLError):
        validate_read_only(sql)


def test_database_executes_select(db):
    assert db.execute("SELECT COUNT(*) FROM customers").rows == [(40,)]


def test_database_rejects_write_before_touching_disk(db):
    with pytest.raises(UnsafeSQLError):
        db.execute("DELETE FROM customers")
    assert db.execute("SELECT COUNT(*) FROM customers").rows == [(40,)]


def test_authorizer_and_readonly_mode_are_independent_layers(db):
    """Even with the lexical check bypassed, the connection itself refuses writes."""
    import sqlite3
    from text2sql.guard import read_only_authorizer

    conn = db._connect()
    try:
        with pytest.raises(sqlite3.OperationalError):  # mode=ro alone
            conn.execute("DELETE FROM customers")
        conn.set_authorizer(read_only_authorizer)
        with pytest.raises(sqlite3.DatabaseError):     # authorizer alone
            conn.execute("DELETE FROM customers")
    finally:
        conn.close()


def test_sql_error_is_wrapped(db):
    with pytest.raises(SQLExecutionError):
        db.execute("SELECT nope FROM customers")


def test_row_limit_truncates(db):
    small = type(db)(db.path, max_rows=5)
    res = small.execute("SELECT * FROM order_items")
    assert len(res.rows) == 5 and res.truncated
