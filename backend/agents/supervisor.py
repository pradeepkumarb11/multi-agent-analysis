"""
backend/agents/supervisor.py

SUPERVISOR — routing brain of the LangGraph pipeline.

In LangGraph the supervisor is split into two parts:
  1. supervisor_node  — async node that publishes a Redis routing event
                        and passes state through unchanged
  2. route_supervisor — pure sync function used as the conditional edge
                        predicate; reads state → returns next node name

Routing logic:
  no plan yet                          → "planner"
  plan exists, no code yet             → "coder"
  critique.approved = True             → END
  critique.approved = False, iter < 3  → "coder"   (retry loop)
  iteration >= 3                       → END         (hard stop)

This separation keeps LangGraph's edge model clean while still
allowing async Redis event publishing inside the node.
"""

import logging
from typing import Any

from langgraph.graph import END

from backend.state import AgentState
from backend.redis_events import publish_event

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 3


# ---------------------------------------------------------------------------
# Routing logic — pure function, no side effects
# Used both inside supervisor_node AND as the conditional edge predicate
# ---------------------------------------------------------------------------


def _decide_next(state: AgentState) -> str:
    """
    Determine the next node based on current state.
    Returns a string: "planner" | "coder" | "__end__" (LangGraph END sentinel)
    """
    plan = state.get("plan", {})
    code = state.get("code", "")
    critique = state.get("critique", {})
    iteration = state.get("iteration", 0)

    # No plan yet → generate one first
    if not plan or not plan.get("steps"):
        logger.debug("Supervisor → planner (no plan)")
        return "planner"

    # Plan exists but no code yet → send to coder for first attempt
    if not code:
        logger.debug("Supervisor → coder (first attempt)")
        return "coder"

    # Hard stop: max iterations exhausted
    if iteration >= MAX_ITERATIONS:
        logger.info("Supervisor → END (iteration limit %d reached)", MAX_ITERATIONS)
        return END

    # Critic approved → pipeline complete
    if critique.get("approved", False):
        logger.info("Supervisor → END (approved, score=%.2f)", critique.get("score", 0))
        return END

    # Critique not yet run (code just generated, no critique key yet)
    # This shouldn't normally hit because graph routes coder → critic → supervisor
    # but guard it anyway
    if not critique:
        logger.debug("Supervisor → coder (no critique yet)")
        return "coder"

    # Not approved, iterations remain → retry coder with issues
    logger.info(
        "Supervisor → coder (retry, iter=%d, score=%.2f, issues=%d)",
        iteration, critique.get("score", 0), len(critique.get("issues", [])),
    )
    return "coder"


# ---------------------------------------------------------------------------
# LangGraph node — publishes event, passes state through unchanged
# ---------------------------------------------------------------------------


async def supervisor_node(state: AgentState) -> dict[str, Any]:
    """
    Async LangGraph node that publishes a routing decision event to Redis.
    Returns an empty dict (no state mutation — supervisor only routes).
    """
    job_id = state.get("job_id", "")
    next_node = _decide_next(state)
    iteration = state.get("iteration", 0)

    # Human-readable routing message for the UI trace
    if next_node == "planner":
        content = "Starting analysis — generating plan..."
    elif next_node == "coder":
        attempt = iteration + 1
        content = f"Routing to coder (attempt {attempt}/3)..."
    else:
        score = state.get("critique", {}).get("score")
        score_str = f" — final score: {score:.2f}" if score is not None else ""
        content = f"Analysis complete{score_str}"

    await publish_event(job_id, {
        "agent": "supervisor",
        "status": "started" if next_node != END else "done",
        "content": content,
        "score": None,
        "iterations": iteration,
    })

    return {}  # no state changes — supervisor only routes


# ---------------------------------------------------------------------------
# Conditional edge predicate — called by LangGraph after supervisor_node runs
# Must be sync and return a key matching the conditional_edges mapping
# ---------------------------------------------------------------------------


def route_supervisor(state: AgentState) -> str:
    """
    Pure routing predicate for LangGraph conditional edges.
    Returns: "planner" | "coder" | END
    """
    return _decide_next(state)
