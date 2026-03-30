"""
backend/worker.py

ARQ background worker — picks up analysis jobs from Upstash Redis queue
and runs the full LangGraph pipeline.

Architecture role:
  FastAPI (API process)
    └─ POST /api/ask → arq.create_pool → enqueue "run_analysis"
                                              │
                                    Upstash Redis queue
                                              │
  ARQ Worker (this process) ←── picks up job
    └─ run_analysis()
         ├─ publishes events to Redis pub/sub channel "job:{job_id}"
         ├─ invokes LangGraph pipeline (all agents)
         └─ saves result to Supabase

Why a separate process?
  LangGraph can take 30–120 seconds to complete (multiple LLM calls).
  If we ran it inside FastAPI, the HTTP request would time out.
  ARQ lets the API return job_id immediately; the browser polls via SSE.

Redis usage — two separate mechanisms:
  ARQ queue  : arq:queue list  — job dispatch (handled by ARQ internally)
  Pub/sub    : "job:{job_id}"  — streaming events to SSE endpoint
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime

from arq import create_pool
from arq.connections import RedisSettings

from backend.graph import pipeline
from backend.redis_events import (
    emit_started,
    emit_error,
    emit_end,
    get_redis,
    close_redis,
)
from backend.db.supabase_client import insert_message
from backend.state import AgentState

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helper: build initial AgentState from job payload
# ---------------------------------------------------------------------------


def _build_initial_state(
    job_id: str,
    question: str,
    upload_id: str,
    session_id: str,
    df_schema: str,
    df_json: str,
) -> AgentState:
    return AgentState(
        messages=[],
        question=question,
        df_schema=df_schema,
        df_json=df_json,
        upload_id=upload_id,
        session_id=session_id,
        job_id=job_id,
        plan={},
        code="",
        result="",
        chart_b64="",
        critique={},
        iteration=0,
        final_report="",
    )


# ---------------------------------------------------------------------------
# Main ARQ task — this is what gets enqueued and executed by the worker
# ---------------------------------------------------------------------------


async def run_analysis(
    ctx: dict,
    job_id: str,
    question: str,
    upload_id: str,
    session_id: str,
    df_schema: str,
    df_json: str,
) -> dict:
    """
    ARQ task: runs the full LangGraph multi-agent pipeline for one question.

    Parameters (all serialised to Redis as JSON by ARQ):
      ctx        : ARQ context dict (contains redis connection etc.)
      job_id     : UUID string — used as Redis pub/sub channel key
      question   : user's natural language question
      upload_id  : Supabase uploads.id
      session_id : Supabase sessions.id
      df_schema  : pre-formatted schema string (cols, dtypes, samples)
      df_json    : full DataFrame as JSON string (orient='records')

    Returns:
      dict with final_report, chart_b64, eval_score, iterations
      (ARQ stores this as the job result, accessible via job.result())
    """
    logger.info(
        "run_analysis START — job_id=%s question=%r session=%s",
        job_id, question[:60], session_id,
    )

    # ----------------------------------------------------------------
    # 1. Announce job start on Redis pub/sub channel
    # ----------------------------------------------------------------
    await emit_started(
        job_id, "supervisor",
        content=f"Job {job_id[:8]}... received. Starting pipeline.",
    )

    initial_state = _build_initial_state(
        job_id=job_id,
        question=question,
        upload_id=upload_id,
        session_id=session_id,
        df_schema=df_schema,
        df_json=df_json,
    )

    final_report = ""
    chart_b64 = ""
    eval_score = 0.0
    iterations = 0

    try:
        # ----------------------------------------------------------------
        # 2. Run LangGraph pipeline (all agents: planner → coder → critic)
        #    ainvoke() resolves after the graph reaches END
        # ----------------------------------------------------------------
        logger.info("Invoking LangGraph pipeline for job %s", job_id)
        final_state: AgentState = await pipeline.ainvoke(initial_state)

        # ----------------------------------------------------------------
        # 3. Extract results from final state
        # ----------------------------------------------------------------
        final_report = final_state.get("final_report", "").strip()
        chart_b64    = final_state.get("chart_b64", "")
        iterations   = final_state.get("iteration", 0)
        critique     = final_state.get("critique", {})
        eval_score   = critique.get("score", 0.0)

        # Fallback report if agent didn't write one
        if not final_report:
            result_stdout = final_state.get("result", "")
            if "STDOUT:" in result_stdout:
                final_report = result_stdout.split("STDOUT:", 1)[1].split("STDERR:")[0].strip()
            if not final_report:
                final_report = (
                    "The analysis completed. "
                    "Please review the chart for visual results."
                    if chart_b64
                    else "Analysis completed with no printed output."
                )

        logger.info(
            "Pipeline complete — job=%s score=%.2f iter=%d chart=%s",
            job_id, eval_score, iterations, "yes" if chart_b64 else "no",
        )

        # ----------------------------------------------------------------
        # 4. Publish terminal END event → SSE endpoint closes stream
        # ----------------------------------------------------------------
        await emit_end(
            job_id=job_id,
            report=final_report,
            chart_b64=chart_b64,
            eval_score=eval_score,
            iterations=iterations,
        )

        # ----------------------------------------------------------------
        # 5. Persist result to Supabase
        # ----------------------------------------------------------------
        try:
            insert_message(
                session_id=session_id,
                upload_id=upload_id,
                question=question,
                final_report=final_report,
                chart_b64=chart_b64,
                eval_score=eval_score,
                iterations=iterations,
            )
            logger.info("Result saved to Supabase for job %s", job_id)
        except Exception as db_exc:
            # DB save failure should NOT crash the worker or lose the result
            logger.error("Failed to save result to Supabase: %s", db_exc)

        return {
            "job_id": job_id,
            "final_report": final_report,
            "chart_b64": chart_b64[:50] + "..." if chart_b64 else "",  # truncate for ARQ result storage
            "eval_score": eval_score,
            "iterations": iterations,
            "status": "completed",
        }

    except Exception as exc:
        logger.exception("run_analysis FAILED — job=%s error=%s", job_id, exc)

        # Publish error event so SSE endpoint can close cleanly
        await emit_error(job_id, "worker", f"Pipeline error: {exc}")

        # Also emit END so SSE connection closes (browser won't hang)
        await emit_end(
            job_id=job_id,
            report=f"An error occurred during analysis: {exc}",
            chart_b64="",
            eval_score=0.0,
            iterations=iterations,
        )

        return {
            "job_id": job_id,
            "status": "failed",
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# ARQ WorkerSettings — Render Background Worker reads this class
# ---------------------------------------------------------------------------


class WorkerSettings:
    """
    ARQ worker configuration.

    Render Background Worker start command:
        arq backend.worker.WorkerSettings

    Upstash Redis URL format:
        rediss://default:<password>@<host>.upstash.io:6379
        (note: rediss:// with TLS, not redis://)
    """

    redis_settings = RedisSettings.from_dsn(
        os.getenv("UPSTASH_REDIS_URL", "redis://localhost:6379")
    )

    functions = [run_analysis]

    # Worker health: retry failed jobs once, then give up
    max_jobs = 10                    # concurrent jobs per worker instance
    job_timeout = 300                # 5-minute hard timeout per job
    keep_result = 3600               # keep job results in Redis for 1 hour
    retry_jobs = True
    max_tries = 2                    # retry once on failure


# ---------------------------------------------------------------------------
# Convenience: enqueue a job from FastAPI (import this in main.py)
# ---------------------------------------------------------------------------


async def enqueue_analysis(
    job_id: str,
    question: str,
    upload_id: str,
    session_id: str,
    df_schema: str,
    df_json: str,
) -> str:
    """
    Enqueue a run_analysis job onto the ARQ queue.
    Returns the job_id (same as input — caller generates it).

    Called from FastAPI POST /api/ask endpoint.
    """
    redis_url = os.getenv("UPSTASH_REDIS_URL", "redis://localhost:6379")
    pool = await create_pool(RedisSettings.from_dsn(redis_url))

    await pool.enqueue_job(
        "run_analysis",
        job_id=job_id,
        question=question,
        upload_id=upload_id,
        session_id=session_id,
        df_schema=df_schema,
        df_json=df_json,
        _job_id=job_id,              # ARQ job ID = our job_id for lookup
    )

    await pool.aclose()
    logger.info("Job %s enqueued for question: %r", job_id, question[:60])
    return job_id
