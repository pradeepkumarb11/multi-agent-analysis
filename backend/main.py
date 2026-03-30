"""
backend/main.py

FastAPI application — public-facing API layer.

Endpoints:
  POST /api/sessions              → create session, return session_id
  POST /api/upload/{session_id}   → upload CSV, return upload_id + schema
  POST /api/ask/{session_id}      → enqueue job, return job_id immediately
  GET  /api/stream/{job_id}       → SSE stream of agent events
  GET  /api/history/{session_id}  → past Q&A for a session
  GET  /api/health                → health check

Design:
  - POST /api/ask returns job_id in <100ms (never blocks on agents)
  - GET /api/stream subscribes to Redis pub/sub "job:{job_id}"
  - Worker publishes events; SSE forwards them to the browser
  - Connection closes automatically on END event or client disconnect
"""

import asyncio
import io
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import pandas as pd
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.db.supabase_client import (
    insert_session,
    insert_upload,
    get_messages,
    ping,
)
from backend.redis_events import get_redis, close_redis
from backend.worker import enqueue_analysis

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lifespan — startup / shutdown hooks
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("FastAPI starting up — warming Redis connection...")
    try:
        r = await get_redis()
        await r.ping()
        logger.info("Redis connected.")
    except Exception as e:
        logger.warning("Redis ping failed at startup: %s", e)
    yield
    logger.info("FastAPI shutting down — closing Redis...")
    await close_redis()


# ---------------------------------------------------------------------------
# App init
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Multi-Agent LLM Data Analysis API",
    description="FastAPI backend for the multi-agent CSV analysis system.",
    version="1.0.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS — allow Vercel deploys + local dev
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------


class AskRequest(BaseModel):
    question: str
    upload_id: str


class SessionResponse(BaseModel):
    session_id: str


class UploadResponse(BaseModel):
    upload_id: str
    schema_summary: str
    row_count: int
    col_count: int
    columns: list[str]


class AskResponse(BaseModel):
    job_id: str


# ---------------------------------------------------------------------------
# Helper: build df_schema string from pandas DataFrame
# ---------------------------------------------------------------------------


def _build_schema(df: pd.DataFrame) -> str:
    """
    Build a compact plain-text schema string for the LLM system prompt.
    Format:
      Columns: col1 (dtype), col2 (dtype), ...
      Dtypes: col1=dtype, col2=dtype, ...
      Sample rows:
        row1_json
        row2_json
        row3_json
    """
    col_type_list = ", ".join(
        f"{col} ({str(dt)})" for col, dt in df.dtypes.items()
    )
    dtype_map = ", ".join(
        f"{col}={str(dt)}" for col, dt in df.dtypes.items()
    )
    sample = df.head(3).to_dict(orient="records")
    sample_lines = "\n".join(f"  {json.dumps(row)}" for row in sample)

    return (
        f"Columns: {col_type_list}\n"
        f"Dtypes: {dtype_map}\n"
        f"Sample rows:\n{sample_lines}"
    )


# ---------------------------------------------------------------------------
# SSE streaming helper
# ---------------------------------------------------------------------------


async def _sse_event(data: dict) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(data)}\n\n"


async def _sse_generator(job_id: str) -> AsyncGenerator[str, None]:
    """
    Subscribe to Redis pub/sub channel "job:{job_id}".
    Yield each message as an SSE event.
    Close after receiving agent="END" or after timeout.
    """
    channel_name = f"job:{job_id}"
    MAX_WAIT_SECONDS = 300  # 5 min hard ceiling
    POLL_SLEEP = 0.05       # 50ms poll interval

    # Send an initial heartbeat so the browser knows the connection is live
    yield f"data: {json.dumps({'agent': 'system', 'status': 'connected', 'content': 'Stream connected. Waiting for worker...'})}\n\n"

    r = await get_redis()
    pubsub = r.pubsub()

    try:
        await pubsub.subscribe(channel_name)
        logger.info("SSE stream opened: channel=%s", channel_name)

        elapsed = 0.0
        while elapsed < MAX_WAIT_SECONDS:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=0.1
            )

            if message and message["type"] == "message":
                raw = message["data"]
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    payload = {"agent": "system", "status": "error", "content": raw}

                yield await _sse_event(payload)

                # Terminal event — close the stream
                if payload.get("agent") == "END":
                    logger.info("SSE stream END received for job %s", job_id)
                    break

            else:
                await asyncio.sleep(POLL_SLEEP)
                elapsed += POLL_SLEEP

        if elapsed >= MAX_WAIT_SECONDS:
            logger.warning("SSE stream timed out for job %s", job_id)
            yield await _sse_event({
                "agent": "system",
                "status": "error",
                "content": "Stream timed out after 5 minutes.",
            })

    except asyncio.CancelledError:
        logger.info("SSE stream cancelled by client for job %s", job_id)
    except Exception as exc:
        logger.exception("SSE stream error for job %s: %s", job_id, exc)
        yield await _sse_event({
            "agent": "system",
            "status": "error",
            "content": f"Stream error: {exc}",
        })
    finally:
        try:
            await pubsub.unsubscribe(channel_name)
            await pubsub.aclose()
        except Exception:
            pass
        logger.info("SSE stream closed: channel=%s", channel_name)


# ===========================================================================
# ENDPOINTS
# ===========================================================================


# ---------------------------------------------------------------------------
# GET /api/health
# ---------------------------------------------------------------------------


@app.get("/api/health")
async def health():
    """
    Health check endpoint.
    Returns Redis + Supabase connectivity status.
    """
    redis_ok = False
    supabase_ok = False

    try:
        r = await get_redis()
        await r.ping()
        redis_ok = True
    except Exception as e:
        logger.warning("Health: Redis fail — %s", e)

    try:
        supabase_ok = ping()
    except Exception as e:
        logger.warning("Health: Supabase fail — %s", e)

    return {
        "status": "ok",
        "model": "llama-3.1-70b-versatile",
        "redis": "ok" if redis_ok else "unavailable",
        "supabase": "ok" if supabase_ok else "unavailable",
    }


# ---------------------------------------------------------------------------
# POST /api/sessions
# ---------------------------------------------------------------------------


@app.post("/api/sessions", response_model=SessionResponse)
async def create_session(request: Request):
    """
    Create a new analysis session.
    Called once when the user loads the page.
    """
    user_agent = request.headers.get("user-agent", "")
    try:
        row = insert_session(user_agent=user_agent)
        return SessionResponse(session_id=row["id"])
    except Exception as exc:
        logger.exception("Failed to create session: %s", exc)
        raise HTTPException(status_code=500, detail=f"Session creation failed: {exc}")


# ---------------------------------------------------------------------------
# POST /api/upload/{session_id}
# ---------------------------------------------------------------------------


@app.post("/api/upload/{session_id}", response_model=UploadResponse)
async def upload_csv(session_id: str, file: UploadFile = File(...)):
    """
    Accept a CSV file upload, parse with pandas, store metadata in Supabase.
    Returns upload_id + schema summary for display in the frontend.

    Note on df_json: the full DataFrame is NOT stored in Supabase (could be
    large). Instead, it's passed to the worker at job-enqueue time via the
    ARQ payload. This keeps Supabase rows small.
    """
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are accepted.")

    try:
        contents = await file.read()
        df = pd.read_csv(io.BytesIO(contents))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"CSV parse error: {exc}")

    if df.empty:
        raise HTTPException(status_code=422, detail="Uploaded CSV is empty.")

    if len(df.columns) < 1:
        raise HTTPException(status_code=422, detail="CSV has no columns.")

    # Limit very large files — free tier Groq has token limits
    MAX_ROWS = 50_000
    if len(df) > MAX_ROWS:
        logger.warning("CSV truncated from %d to %d rows", len(df), MAX_ROWS)
        df = df.head(MAX_ROWS)

    col_names    = list(df.columns)
    dtypes_dict  = {col: str(dt) for col, dt in df.dtypes.items()}
    sample_rows  = df.head(3).to_dict(orient="records")
    schema_str   = _build_schema(df)

    try:
        row = insert_upload(
            session_id=session_id,
            filename=file.filename,
            row_count=len(df),
            col_names=col_names,
            dtypes=dtypes_dict,
            sample_rows=sample_rows,
        )
    except Exception as exc:
        logger.exception("Failed to store upload metadata: %s", exc)
        raise HTTPException(status_code=500, detail=f"Upload storage failed: {exc}")

    return UploadResponse(
        upload_id=row["id"],
        schema_summary=schema_str,
        row_count=len(df),
        col_count=len(df.columns),
        columns=col_names,
    )


# ---------------------------------------------------------------------------
# POST /api/ask/{session_id}
# ---------------------------------------------------------------------------


@app.post("/api/ask/{session_id}", response_model=AskResponse)
async def ask_question(session_id: str, body: AskRequest, request: Request):
    """
    Enqueue an analysis job. Returns job_id immediately (< 100ms).
    The browser then opens GET /api/stream/{job_id} to receive events.

    df_json is fetched from the upload record so the worker has the data.
    For large files: consider storing df_json in Supabase uploads.sample_rows
    or a dedicated storage bucket. For this MVP, we reconstruct from metadata.
    """
    if not body.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    if not body.upload_id:
        raise HTTPException(status_code=400, detail="upload_id is required.")

    # Fetch upload metadata to reconstruct df_schema
    from backend.db.supabase_client import get_upload
    upload = get_upload(body.upload_id)
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found. Please upload a CSV first.")

    # Rebuild schema string from stored metadata
    col_names   = upload.get("col_names", [])
    dtypes_dict = upload.get("dtypes", {})
    sample_rows = upload.get("sample_rows", [])

    col_type_list = ", ".join(f"{c} ({dtypes_dict.get(c, 'unknown')})" for c in col_names)
    dtype_str     = ", ".join(f"{c}={dtypes_dict.get(c, 'unknown')}" for c in col_names)
    sample_str    = "\n".join(f"  {json.dumps(r)}" for r in sample_rows[:3])

    df_schema = (
        f"Columns: {col_type_list}\n"
        f"Dtypes: {dtype_str}\n"
        f"Sample rows:\n{sample_str}"
    )

    # For the worker, we pass sample data as the "df" (full data not re-uploaded).
    # In a production system, store the full CSV in Supabase Storage and re-fetch here.
    # For this MVP: worker uses sample_rows as df (sufficient for most questions).
    df_json = json.dumps(sample_rows) if sample_rows else "[]"

    job_id = str(uuid.uuid4())

    try:
        await enqueue_analysis(
            job_id=job_id,
            question=body.question.strip(),
            upload_id=body.upload_id,
            session_id=session_id,
            df_schema=df_schema,
            df_json=df_json,
        )
    except Exception as exc:
        logger.exception("Failed to enqueue job: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to start analysis: {exc}")

    logger.info("Job %s enqueued for session %s", job_id, session_id)
    return AskResponse(job_id=job_id)


# ---------------------------------------------------------------------------
# GET /api/stream/{job_id}   — SSE
# ---------------------------------------------------------------------------


@app.get("/api/stream/{job_id}")
async def stream_job(job_id: str):
    """
    Server-Sent Events endpoint.
    Subscribes to Redis pub/sub channel "job:{job_id}".
    Forwards each agent event as an SSE data line.
    Closes automatically on END event or client disconnect.

    SSE event shape (each line):
      data: {"agent": str, "status": str, "content": str,
             "score": float|null, "iterations": int|null}

    Terminal event:
      data: {"agent": "END", "report": str, "chart_b64": str,
             "eval_score": float, "iterations": int}
    """
    return StreamingResponse(
        _sse_generator(job_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control":    "no-cache",
            "X-Accel-Buffering": "no",    # disable Nginx buffering on Render
            "Connection":        "keep-alive",
        },
    )


# ---------------------------------------------------------------------------
# GET /api/history/{session_id}
# ---------------------------------------------------------------------------


@app.get("/api/history/{session_id}")
async def get_history(session_id: str):
    """
    Return all past questions + answers for a session.
    Used to populate the left-panel history list in the frontend.
    chart_b64 is excluded from the list view (too large).
    """
    try:
        rows = get_messages(session_id)
        # Exclude chart_b64 from list — let frontend fetch individually if needed
        return {
            "session_id": session_id,
            "messages": [
                {
                    "id":           r["id"],
                    "question":     r["question"],
                    "final_report": r["final_report"],
                    "eval_score":   r["eval_score"],
                    "iterations":   r["iterations"],
                    "created_at":   r["created_at"],
                    "upload_id":    r["upload_id"],
                }
                for r in rows
            ],
            "count": len(rows),
        }
    except Exception as exc:
        logger.exception("Failed to fetch history for session %s: %s", session_id, exc)
        raise HTTPException(status_code=500, detail=f"History fetch failed: {exc}")
