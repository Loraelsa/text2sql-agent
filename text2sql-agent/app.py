"""Streamlit demo:  streamlit run app.py"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent / "src"))

from text2sql.agent import Text2SQLAgent  # noqa: E402
from text2sql.db import Database  # noqa: E402
from text2sql.llm import OPENAI_COMPAT, get_llm  # noqa: E402
from text2sql.sample_db import DEFAULT_PATH, ensure_sample_db  # noqa: E402

st.set_page_config(page_title="Text-to-SQL Agent", page_icon="🔎", layout="wide")
st.title("🔎 Text-to-SQL Agent")
st.caption("Ask questions in plain English. The agent writes read-only SQL, runs it, and fixes its own errors.")

EXAMPLES = [
    "Which product category generated the most revenue from delivered orders?",
    "Which customers have spent more than 10000 in total on delivered orders?",
    "For each month of 2025, how many orders were placed?",
    "Which products have never been ordered?",
]

with st.sidebar:
    st.header("Settings")
    provider = st.selectbox("LLM provider", ["anthropic", *OPENAI_COMPAT])
    model = st.text_input("Model (optional)", help="Leave blank for the provider default.")
    st.markdown("**Agent features**")
    prune = st.toggle("Schema pruning", value=True)
    self_correct = st.toggle("Self-correction", value=True)
    explain = st.toggle("Plain-English explanation", value=True)
    st.markdown("**Database**")
    upload = st.file_uploader("Upload your own SQLite file", type=["db", "sqlite", "sqlite3"])
    st.caption("Queries run read-only: single SELECT statements only.")


@st.cache_resource
def _sample_path() -> str:
    return str(ensure_sample_db(DEFAULT_PATH))


if upload is not None:
    tmp = Path(tempfile.gettempdir()) / f"upload_{upload.file_id}.db"
    tmp.write_bytes(upload.getvalue())
    db_path = str(tmp)
else:
    db_path = _sample_path()

try:
    db = Database(db_path)
    probe = Text2SQLAgent(db, llm=None, prune=prune, self_correct=self_correct)  # type: ignore[arg-type]
except Exception as exc:  # noqa: BLE001
    st.error(f"Could not open that database: {exc}")
    st.stop()

with st.expander("Database schema", expanded=False):
    for t in probe.tables:
        st.markdown(f"**{t.name}** — " + ", ".join(f"`{c.name}`" for c in t.columns))

if "question" not in st.session_state:
    st.session_state.question = ""
if upload is None:
    st.write("Try an example:")
    cols = st.columns(len(EXAMPLES))
    for col, ex in zip(cols, EXAMPLES):
        if col.button(ex, width="stretch"):
            st.session_state.question = ex

question = st.text_input("Your question", key="question", placeholder="e.g. How many customers are there?")

if st.button("Ask", type="primary", disabled=not question.strip()):
    try:
        agent = Text2SQLAgent(db, get_llm(provider, model or None), prune=prune, self_correct=self_correct)
        with st.spinner("Thinking..."):
            res = agent.ask(question, explain=explain)
    except Exception as exc:  # noqa: BLE001 - usually a missing API key
        st.error(f"{type(exc).__name__}: {exc}")
        st.stop()

    st.caption(f"Schema sent to the model: {', '.join(res.schema_tables)} · {res.latency_s:.1f}s")
    if res.success:
        if res.explanation:
            st.success(res.explanation)
        st.dataframe(pd.DataFrame(res.rows, columns=res.columns), width="stretch")
        if res.truncated:
            st.info("Results truncated to the first rows.")
    else:
        st.error(f"Could not produce a working query. Last error: {res.error}")

    with st.expander(f"SQL and self-correction trace ({len(res.attempts)} attempt(s))", expanded=not res.success):
        for i, a in enumerate(res.attempts, 1):
            st.markdown(f"**Attempt {i}** — {'✅ ok' if a.error is None else '❌ ' + a.error}")
            st.code(a.sql, language="sql")
