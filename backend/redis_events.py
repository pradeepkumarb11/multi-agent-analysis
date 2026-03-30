"""
backend/redis_events.py

Thin async wrapper for publishing agent progress events to Redis pub/sub.

Every agent node calls publish_event() with a structured dict.
The FastAPI SSE endpoint subscribes to the same channel and
forwards events to the browser.

Channel naming convention:  "job:{job_id}"
"""

import json
import logging
import os
from typing import Any

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Async Redis client — created lazily, shared across the worker process
# ---------------------------------------------------------------------------

_redis_client: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    """Return a cached async Redis client."""
    global _redis_client
    if _redis_client is None:
        url = os.getenv("UPSTASH_REDIS_URL")
        if not url:
            raise EnvironmentError("UPSTASH_REDIS_URL environment variable is not set.")
        _redis_client = aioredis.from_url(
            url,
            encoding="utf-8",
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=5,
        )
        logger.info("Async Redis client initialized.")
    return _redis_client


async def close_redis() -> None:
    """Close the Redis connection pool gracefully."""
    global _redis_client
    if _redis_client:
        await _redis_client.aclose()
        _redis_client = None


# ---------------------------------------------------------------------------
# Core publish helper
# ---------------------------------------------------------------------------


async def publish_event(job_id: str, payload: dict[str, Any]) -> None:
    """
    Publish a JSON-serialised event dict to the Redis channel for job_id.

    All agents call this after start / completion / error.
    The SSE endpoint subscribes and forwards these to the browser.

    Parameters
    ----------
    job_id  : str  — used as channel suffix: "job:{job_id}"
    payload : dict — must contain at minimum {"agent": str, "status": str}
    """
    channel = f"job:{job_id}"
    message = json.dumps(payload, ensure_ascii=False)
    try:
        r = await get_redis()
        await r.publish(channel, message)
        logger.debug("Published to %s: %s", channel, message[:120])
    except Exception as exc:
        # Never let a publish failure crash the agent pipeline
        logger.error("Failed to publish event to %s: %s", channel, exc)


# ---------------------------------------------------------------------------
# Convenience wrappers — agents call these instead of raw publish_event
# ---------------------------------------------------------------------------


async def emit_started(job_id: str, agent: str, content: str = "") -> None:
    await publish_event(job_id, {
        "agent": agent,
        "status": "started",
        "content": content,
        "score": None,
        "iterations": None,
    })


async def emit_done(
    job_id: str,
    agent: str,
    content: str = "",
    score: float | None = None,
    iterations: int | None = None,
) -> None:
    await publish_event(job_id, {
        "agent": agent,
        "status": "done",
        "content": content,
        "score": score,
        "iterations": iterations,
    })


async def emit_error(job_id: str, agent: str, error: str) -> None:
    await publish_event(job_id, {
        "agent": agent,
        "status": "error",
        "content": error,
        "score": None,
        "iterations": None,
    })


async def emit_end(
    job_id: str,
    report: str,
    chart_b64: str,
    eval_score: float,
    iterations: int,
) -> None:
    """Final terminal event — SSE subscriber closes after receiving this."""
    await publish_event(job_id, {
        "agent": "END",
        "status": "done",
        "report": report,
        "chart_b64": chart_b64,
        "eval_score": eval_score,
        "iterations": iterations,
    })
