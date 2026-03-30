"""
backend/agents/critic.py

CRITIC agent — quality gate and feedback loop of the LangGraph pipeline.

Responsibilities:
- Evaluates the coder's output across 3 axes (0.0–1.0 each):
    correctness  : did the code execute without errors?
    relevance    : does the output actually answer the question?
    completeness : were all plan steps attempted?
- Computes final score = mean(correctness, relevance, completeness)
- Returns structured Critique via with_structured_output(Critique)
- Sets approved=True if score >= 0.75 OR iteration >= 3 (hard stop)
- Publishes Redis event with score + approved status

Model choice rationale:
  Scoring/critique is a lighter reasoning task than code generation —
  llama-3.1-8b-instant is fast and sufficient for rubric-based evaluation.
"""

import logging
import os
from typing import Any

from langchain_groq import ChatGroq
from pydantic import BaseModel, Field

from backend.state import AgentState
from backend.redis_events import emit_started, emit_done, emit_error

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 3
APPROVAL_THRESHOLD = 0.75

# ---------------------------------------------------------------------------
# Pydantic schema for structured output
# ---------------------------------------------------------------------------


class Critique(BaseModel):
    """Structured quality assessment returned by the critic LLM."""

    correctness: float = Field(
        ge=0.0, le=1.0,
        description=(
            "Score 0.0–1.0. Did the code run without errors? "
            "1.0 = no errors. 0.0 = crashed or timed out. "
            "Partial credit for minor warnings."
        )
    )
    relevance: float = Field(
        ge=0.0, le=1.0,
        description=(
            "Score 0.0–1.0. Does the output directly answer the user's question? "
            "1.0 = fully answers the question. 0.5 = partial answer. 0.0 = unrelated."
        )
    )
    completeness: float = Field(
        ge=0.0, le=1.0,
        description=(
            "Score 0.0–1.0. Were all steps in the analysis plan attempted? "
            "1.0 = all steps complete. Deduct proportionally for skipped steps."
        )
    )
    score: float = Field(
        ge=0.0, le=1.0,
        description="Final score: mean of correctness, relevance, completeness."
    )
    issues: list[str] = Field(
        default_factory=list,
        description=(
            "List of specific, actionable issues the coder must fix in the next attempt. "
            "Empty if approved. Be precise: name the variable, column, or output that is wrong."
        )
    )
    approved: bool = Field(
        description=(
            "True if score >= 0.75 OR the iteration limit has been reached. "
            "False means the coder should retry with the issues list."
        )
    )


# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a rigorous data analysis critic evaluating whether a Python analysis \
correctly answers a user's question.

You will receive:
  1. The user's original question
  2. The analysis plan (ordered steps)
  3. The Python code that was generated
  4. The code's execution output (stdout + stderr)

Score the analysis on 3 axes, each 0.0–1.0:

  CORRECTNESS (did the code run without errors?)
    1.0 = clean execution, no errors
    0.5 = ran but with non-fatal warnings  
    0.0 = crashed, SyntaxError, NameError, Timeout, or empty output from error

  RELEVANCE (does the output answer the user's question?)
    1.0 = directly and completely answers the question
    0.5 = partially answers or answers a related but different question
    0.0 = output is unrelated to the question

  COMPLETENESS (were all plan steps attempted?)
    1.0 = all plan steps executed
    0.5 = roughly half the steps executed
    0.0 = plan was completely ignored

Compute: score = (correctness + relevance + completeness) / 3

List only SPECIFIC, ACTIONABLE issues for the coder to fix.
Do not repeat what was done correctly. Do not be vague.
If there are no issues, return an empty list.

Approved = True if score >= 0.75. Otherwise False.
"""

_USER_TEMPLATE = """\
QUESTION: {question}

PLAN:
{plan_steps}

GENERATED CODE:
```python
{code}
```

EXECUTION OUTPUT:
STDOUT:
{stdout}

STDERR:
{stderr}
"""


def _split_result(result: str) -> tuple[str, str]:
    """Split the combined 'STDOUT:\\n...\\nSTDERR:\\n...' result string."""
    stdout, stderr = "", ""
    if "STDOUT:" in result:
        parts = result.split("STDOUT:", 1)
        remainder = parts[1]
        if "STDERR:" in remainder:
            s_parts = remainder.split("STDERR:", 1)
            stdout = s_parts[0].strip()
            stderr = s_parts[1].strip()
        else:
            stdout = remainder.strip()
    else:
        stdout = result.strip()
    return stdout, stderr


# ---------------------------------------------------------------------------
# Agent node
# ---------------------------------------------------------------------------


async def critic_node(state: AgentState) -> dict[str, Any]:
    """
    LangGraph node: scores the coder's output and decides whether to approve.

    Publishes Redis events:
      - "critic" / "started"  — before LLM call
      - "critic" / "done"     — after scoring, includes score + approved
      - "critic" / "error"    — on any exception
    """
    job_id = state.get("job_id", "")
    question = state["question"]
    plan = state.get("plan", {})
    code = state.get("code", "")
    result = state.get("result", "")
    iteration = state.get("iteration", 1)

    await emit_started(
        job_id, "critic",
        content=f"Evaluating analysis quality (attempt {iteration}/3)...",
    )

    try:
        # ----------------------------------------------------------------
        # Build prompt
        # ----------------------------------------------------------------
        plan_steps = "\n".join(
            f"  {i}. {step}"
            for i, step in enumerate(plan.get("steps", []), 1)
        ) or "  (no plan provided)"

        stdout, stderr = _split_result(result)

        user_content = _USER_TEMPLATE.format(
            question=question,
            plan_steps=plan_steps,
            code=code[:2000],     # truncate very long code
            stdout=stdout[:1500],
            stderr=stderr[:500],
        )

        # ----------------------------------------------------------------
        # LLM call with structured output
        # ----------------------------------------------------------------
        llm = ChatGroq(
            model="llama-3.1-8b-instant",
            temperature=0.2,
            api_key=os.getenv("GROQ_API_KEY"),
        )
        structured_llm = llm.with_structured_output(Critique)

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": user_content},
        ]

        critique: Critique = await structured_llm.ainvoke(messages)

        # ----------------------------------------------------------------
        # Recompute score server-side (don't trust LLM arithmetic)
        # ----------------------------------------------------------------
        computed_score = round(
            (critique.correctness + critique.relevance + critique.completeness) / 3, 4
        )
        # Hard stop: force approve if we've exhausted iterations
        force_approve = iteration >= MAX_ITERATIONS
        approved = force_approve or (computed_score >= APPROVAL_THRESHOLD)

        critique_dict = {
            "correctness":  critique.correctness,
            "relevance":    critique.relevance,
            "completeness": critique.completeness,
            "score":        computed_score,
            "issues":       critique.issues if not approved else [],
            "approved":     approved,
        }

        # ----------------------------------------------------------------
        # Emit result event
        # ----------------------------------------------------------------
        status_msg = (
            f"Score: {computed_score:.2f} — "
            + ("APPROVED" if approved else f"{len(critique.issues)} issue(s) found")
        )
        if force_approve and not (computed_score >= APPROVAL_THRESHOLD):
            status_msg += " (iteration limit reached, forcing approval)"

        await emit_done(
            job_id, "critic",
            content=status_msg,
            score=computed_score,
            iterations=iteration,
        )

        logger.info(
            "Critic: job=%s iter=%d score=%.2f approved=%s issues=%d",
            job_id, iteration, computed_score, approved, len(critique.issues),
        )

        return {
            "critique": critique_dict,
            "messages": state.get("messages", []) + [
                {
                    "role": "assistant",
                    "content": (
                        f"Critique — score: {computed_score:.2f}, "
                        f"approved: {approved}, "
                        f"issues: {critique.issues}"
                    ),
                }
            ],
        }

    except Exception as exc:
        logger.exception("Critic agent failed for job %s: %s", job_id, exc)
        await emit_error(job_id, "critic", str(exc))
        # On critic failure: force approve so pipeline doesn't loop forever
        return {
            "critique": {
                "correctness": 0.0,
                "relevance": 0.0,
                "completeness": 0.0,
                "score": 0.0,
                "issues": [f"Critic agent error: {exc}"],
                "approved": True,  # fail-safe: don't loop infinitely
            }
        }
