"""
backend/agents/planner.py

PLANNER agent — first node in the LangGraph pipeline.

Responsibilities:
- Receives the user's question + df_schema
- Produces a structured list of analysis steps (Plan)
- Uses llama-3.1-8b-instant (fast, cheap) with structured output
- Publishes Redis events: started → done (or error)

Model choice rationale:
  Planning is a lightweight reasoning task — 8B is accurate enough
  and ~3x faster than 70B, saving the bigger model for code generation.
"""

import asyncio
import logging
import os
from typing import Any

from langchain_groq import ChatGroq
from pydantic import BaseModel, Field

from backend.state import AgentState
from backend.redis_events import emit_started, emit_done, emit_error

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pydantic schema for structured output
# ---------------------------------------------------------------------------


class Plan(BaseModel):
    """Structured analysis plan returned by the planner LLM."""

    steps: list[str] = Field(
        description=(
            "Ordered list of concrete analysis steps to answer the question. "
            "Each step should be a specific, actionable instruction for a Python "
            "data analyst. 3–6 steps is ideal."
        )
    )


# ---------------------------------------------------------------------------
# System prompt template
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a senior data analyst planning how to answer a user's question \
about a dataset.

Dataset schema:
{df_schema}

Your task:
- Break the question into 3–6 concrete, ordered analysis steps.
- Each step must be specific enough that a Python coder can implement it \
directly using pandas and matplotlib.
- Do NOT write code — only plan the steps.
- Steps should be sequential and non-redundant.
- The last step should always be: "Summarise findings in plain English."

Respond ONLY with the structured JSON plan. No prose, no explanation.
"""

# ---------------------------------------------------------------------------
# Agent node
# ---------------------------------------------------------------------------


async def planner_node(state: AgentState) -> dict[str, Any]:
    """
    LangGraph node: receives state, returns partial state update.

    Publishes Redis events:
      - "planner" / "started" — before LLM call
      - "planner" / "done"    — after successful plan
      - "planner" / "error"   — on any exception
    """
    job_id = state.get("job_id", "")
    question = state["question"]
    df_schema = state["df_schema"]

    await emit_started(job_id, "planner", content=f"Planning analysis for: {question[:80]}")

    try:
        # ----------------------------------------------------------------
        # Build LLM with structured output binding
        # ----------------------------------------------------------------
        llm = ChatGroq(
            model="llama-3.1-8b-instant",
            temperature=0.2,
            api_key=os.getenv("GROQ_API_KEY"),
        )
        structured_llm = llm.with_structured_output(Plan)

        # ----------------------------------------------------------------
        # Invoke LLM
        # ----------------------------------------------------------------
        system_prompt = _SYSTEM_PROMPT.format(df_schema=df_schema)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
        ]

        plan: Plan = await structured_llm.ainvoke(messages)

        logger.info("Planner produced %d steps for job %s", len(plan.steps), job_id)

        steps_preview = " → ".join(plan.steps[:3])
        if len(plan.steps) > 3:
            steps_preview += f" … (+{len(plan.steps) - 3} more)"

        await emit_done(
            job_id,
            "planner",
            content=f"Plan ready ({len(plan.steps)} steps): {steps_preview}",
        )

        return {
            "plan": plan.model_dump(),          # {"steps": [...]}
            "messages": state.get("messages", []) + [
                {"role": "assistant", "content": f"Plan: {plan.steps}"}
            ],
        }

    except Exception as exc:
        logger.exception("Planner failed for job %s: %s", job_id, exc)
        await emit_error(job_id, "planner", str(exc))
        # Return empty plan so supervisor can handle gracefully
        return {
            "plan": {"steps": []},
        }
