"""
backend/db/supabase_client.py
Thin wrapper around the Supabase Python client.
All DB operations go through these helpers — no raw SQL elsewhere.
"""

import os
import logging
from typing import Any

from supabase import create_client, Client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Singleton client — created once at import time
# ---------------------------------------------------------------------------

_client: Client | None = None


def get_client() -> Client:
    """Return a cached Supabase client, creating it on first call."""
    global _client
    if _client is None:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        if not url or not key:
            raise EnvironmentError(
                "SUPABASE_URL and SUPABASE_KEY must be set in environment variables."
            )
        _client = create_client(url, key)
        logger.info("Supabase client initialized — connected to %s", url)
    return _client


# ---------------------------------------------------------------------------
# sessions table helpers
# ---------------------------------------------------------------------------


def insert_session(user_agent: str = "") -> dict:
    """
    Create a new session row.
    Returns the full row dict including the generated UUID.
    """
    client = get_client()
    response = (
        client.table("sessions")
        .insert({"user_agent": user_agent})
        .execute()
    )
    row = response.data[0]
    logger.debug("Session created: %s", row["id"])
    return row


def get_session(session_id: str) -> dict | None:
    """Fetch a session by ID. Returns None if not found."""
    client = get_client()
    response = (
        client.table("sessions")
        .select("*")
        .eq("id", session_id)
        .single()
        .execute()
    )
    return response.data


# ---------------------------------------------------------------------------
# uploads table helpers
# ---------------------------------------------------------------------------


def insert_upload(
    session_id: str,
    filename: str,
    row_count: int,
    col_names: list,
    dtypes: dict,
    sample_rows: list,
) -> dict:
    """
    Store CSV metadata after upload.
    Returns the full row dict including the generated upload_id UUID.
    """
    client = get_client()
    response = (
        client.table("uploads")
        .insert(
            {
                "session_id": session_id,
                "filename": filename,
                "row_count": row_count,
                "col_names": col_names,
                "dtypes": dtypes,
                "sample_rows": sample_rows,
            }
        )
        .execute()
    )
    row = response.data[0]
    logger.debug("Upload stored: %s (%d rows)", row["id"], row_count)
    return row


def get_upload(upload_id: str) -> dict | None:
    """Fetch upload metadata by ID."""
    client = get_client()
    response = (
        client.table("uploads")
        .select("*")
        .eq("id", upload_id)
        .single()
        .execute()
    )
    return response.data


# ---------------------------------------------------------------------------
# messages table helpers
# ---------------------------------------------------------------------------


def insert_message(
    session_id: str,
    upload_id: str,
    question: str,
    final_report: str,
    chart_b64: str,
    eval_score: float,
    iterations: int,
) -> dict:
    """
    Persist the final result of an agent run.
    Returns the saved row dict.
    """
    client = get_client()
    response = (
        client.table("messages")
        .insert(
            {
                "session_id": session_id,
                "upload_id": upload_id,
                "question": question,
                "final_report": final_report,
                "chart_b64": chart_b64,
                "eval_score": eval_score,
                "iterations": iterations,
            }
        )
        .execute()
    )
    row = response.data[0]
    logger.debug("Message stored: %s (score=%.2f)", row["id"], eval_score)
    return row


def get_messages(session_id: str) -> list[dict]:
    """
    Fetch all messages for a session ordered oldest-first.
    Returns a list of row dicts (may be empty).
    """
    client = get_client()
    response = (
        client.table("messages")
        .select("id, question, final_report, eval_score, iterations, created_at, upload_id")
        .eq("session_id", session_id)
        .order("created_at", desc=False)
        .execute()
    )
    return response.data or []


# ---------------------------------------------------------------------------
# Health-check helper — used by GET /api/health
# ---------------------------------------------------------------------------


def ping() -> bool:
    """
    Quick connectivity check.
    Returns True if we can query Supabase, False otherwise.
    """
    try:
        client = get_client()
        client.table("sessions").select("id").limit(1).execute()
        return True
    except Exception as exc:
        logger.error("Supabase ping failed: %s", exc)
        return False
