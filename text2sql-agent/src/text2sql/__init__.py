"""text2sql-agent: a self-correcting, read-only natural-language-to-SQL agent."""

from .agent import AgentResult, Attempt, Text2SQLAgent, extract_sql
from .db import Database, QueryResult, SQLExecutionError
from .guard import UnsafeSQLError, validate_read_only
from .llm import ScriptedLLM, get_llm

__all__ = [
    "AgentResult", "Attempt", "Text2SQLAgent", "extract_sql",
    "Database", "QueryResult", "SQLExecutionError",
    "UnsafeSQLError", "validate_read_only",
    "ScriptedLLM", "get_llm",
]
__version__ = "0.1.0"
