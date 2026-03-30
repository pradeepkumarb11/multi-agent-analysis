"""
backend/state.py

Shared AgentState TypedDict — single source of truth for LangGraph.
All agent nodes read from and write to this typed dict.
"""

from typing import TypedDict


class AgentState(TypedDict):
    # Core input
    messages:     list        # conversation history (LangChain message objects)
    question:     str         # user's natural language question
    df_schema:    str         # col names + dtypes + 3 sample rows (plain text)
    df_json:      str         # full DataFrame as JSON (passed to code runner)
    upload_id:    str         # Supabase upload row ID
    session_id:   str         # Supabase session row ID
    job_id:       str         # Redis channel key: f"job:{job_id}"

    # Agent outputs (accumulated across nodes)
    plan:         dict        # {"steps": ["...", "..."]}
    code:         str         # latest generated Python code
    result:       str         # stdout captured from code execution
    chart_b64:    str         # base64 PNG (empty string if no chart)
    critique:     dict        # {"score": float, "issues": [], "approved": bool, ...}
    iteration:    int         # retry counter; hard max = 3
    final_report: str         # prose answer written by coder/critic
