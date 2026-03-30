"""
backend/agents/coder.py

CODER agent — the execution engine of the LangGraph pipeline.

Responsibilities:
- Receives the plan + df_schema + (on retry) critique issues
- Generates executable Python code using llama-3.1-70b-versatile
- Runs code via the sandboxed code_runner (subprocess, 10s timeout)
- Captures matplotlib chart as base64 if one is produced
- Publishes 3 Redis events: started → code_generated → executed
- On retry: injects previous critique issues into the prompt

Model choice rationale:
  llama-3.1-70B has strong code generation — significantly better than
  8B for multi-step pandas + matplotlib tasks. Temperature=0 for
  deterministic, reproducible code output.
"""

import asyncio
import logging
import os
import re
from typing import Any

from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage

from backend.state import AgentState
from backend.tools.code_runner import run_code
from backend.redis_events import emit_started, emit_done, emit_error, publish_event

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt — exact wording matters for grounding the LLM
# ---------------------------------------------------------------------------

_SYSTEM_TEMPLATE = """\
You are a Python data analyst. The dataframe is already loaded as the \
variable 'df'. Do not load any files.

Column names: {col_names}
Dtypes: {dtypes}
Sample rows (first 3):
{sample_rows}

Analysis plan to follow:
{plan_steps}

Rules:
- Use pandas for all data manipulation.
- Use matplotlib for charts. Save any chart to a variable named 'fig'. \
  Do NOT call plt.show().
- Print key findings to stdout using print() so they are captured.
- Return ONLY executable Python code, no explanation, no markdown fences.
- Do NOT import pandas or matplotlib — they are already imported.
- Do NOT read any files — 'df' is already loaded.
- Your code must be complete: it must run without any additional input.
"""

_RETRY_ADDENDUM = """\

Previous attempt had these issues — fix all of them:
{issues}
"""

# ---------------------------------------------------------------------------
# Helper: extract raw code from LLM response
# LLM sometimes wraps in ```python ... ``` despite instructions
# ---------------------------------------------------------------------------


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences if the LLM adds them anyway."""
    # Match ```python ... ``` or ``` ... ```
    pattern = r"^```(?:python)?\n?(.*?)```$"
    match = re.match(pattern, text.strip(), re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


# ---------------------------------------------------------------------------
# Helper: build df_schema components from state
# ---------------------------------------------------------------------------


def _parse_schema(df_schema: str) -> tuple[str, str, str]:
    """
    df_schema is a pre-formatted plain-text string built in main.py.
    We pass it through directly — no re-parsing needed.
    Returns (col_names, dtypes, sample_rows) as strings.
    """
    # df_schema format set in main.py:
    # "Columns: col1 (dtype), col2 (dtype), ...\nSample rows:\n  row1\n  row2\n  row3"
    lines = df_schema.splitlines()
    col_names = ""
    dtypes = ""
    sample_rows_lines = []
    in_samples = False

    for line in lines:
        if line.startswith("Columns:"):
            col_names = line.replace("Columns:", "").strip()
        elif line.startswith("Dtypes:"):
            dtypes = line.replace("Dtypes:", "").strip()
        elif line.startswith("Sample rows:"):
            in_samples = True
        elif in_samples:
            sample_rows_lines.append(line)

    sample_rows = "\n".join(sample_rows_lines) if sample_rows_lines else df_schema

    # Fallback: if schema format differs, just use the whole string
    if not col_names:
        col_names = df_schema[:200]
        dtypes = "see schema"
        sample_rows = df_schema

    return col_names, dtypes, sample_rows


# ---------------------------------------------------------------------------
# Agent node
# ---------------------------------------------------------------------------


async def coder_node(state: AgentState) -> dict[str, Any]:
    """
    LangGraph node: generates + executes Python data analysis code.

    Publishes Redis events:
      - "coder" / "started"        — before LLM call
      - "coder" / "code_generated" — after LLM returns code
      - "coder" / "done"           — after code executed successfully
      - "coder" / "error"          — on any failure
    """
    job_id = state.get("job_id", "")
    question = state["question"]
    df_schema = state["df_schema"]
    df_json = state.get("df_json", "")
    plan = state.get("plan", {})
    critique = state.get("critique", {})
    iteration = state.get("iteration", 0)

    iteration += 1  # increment before running

    await emit_started(
        job_id,
        "coder",
        content=f"Generating Python code (attempt {iteration}/3)...",
    )

    try:
        # ----------------------------------------------------------------
        # Build system prompt
        # ----------------------------------------------------------------
        col_names, dtypes, sample_rows = _parse_schema(df_schema)
        plan_steps = "\n".join(
            f"  {i}. {step}"
            for i, step in enumerate(plan.get("steps", []), 1)
        ) or "  1. Analyse the data and answer the question."

        system_content = _SYSTEM_TEMPLATE.format(
            col_names=col_names,
            dtypes=dtypes,
            sample_rows=sample_rows,
            plan_steps=plan_steps,
        )

        # On retry: inject previous issues
        if iteration > 1 and critique.get("issues"):
            issues_text = "\n".join(f"  - {i}" for i in critique["issues"])
            system_content += _RETRY_ADDENDUM.format(issues=issues_text)
            logger.info("Coder retry %d with %d issues injected.", iteration, len(critique["issues"]))

        # ----------------------------------------------------------------
        # LLM call — generate Python code
        # ----------------------------------------------------------------
        llm = ChatGroq(
            model="llama-3.1-70b-versatile",
            temperature=0,
            api_key=os.getenv("GROQ_API_KEY"),
        )

        messages = [
            SystemMessage(content=system_content),
            HumanMessage(content=question),
        ]

        response = await llm.ainvoke(messages)
        raw_code = response.content

        # Strip markdown fences if LLM ignores instructions
        code = _strip_code_fences(raw_code)

        logger.info(
            "Coder generated %d lines of code for job %s (iter %d)",
            len(code.splitlines()), job_id, iteration,
        )

        # Publish code_generated event (content = first 200 chars of code preview)
        await publish_event(job_id, {
            "agent": "coder",
            "status": "code_generated",
            "content": code[:300] + ("..." if len(code) > 300 else ""),
            "score": None,
            "iterations": iteration,
        })

        # ----------------------------------------------------------------
        # Execute code in sandboxed subprocess
        # ----------------------------------------------------------------
        await asyncio.sleep(0)  # yield event loop before blocking subprocess

        # run_code is sync — run in thread pool so we don't block async loop
        loop = asyncio.get_event_loop()
        run_result = await loop.run_in_executor(
            None, lambda: run_code(code=code, df_json=df_json)
        )

        stdout = run_result["stdout"]
        stderr = run_result["stderr"]
        chart_b64 = run_result["chart_b64"]
        success = run_result["success"]

        if success:
            result_summary = stdout[:500] if stdout else "(no printed output)"
            await emit_done(
                job_id,
                "coder",
                content=f"Code executed successfully. Output: {result_summary[:200]}",
                iterations=iteration,
            )
        else:
            # Execution failed — still return state so critic can score it
            error_summary = stderr[:300] if stderr else "Unknown execution error."
            await publish_event(job_id, {
                "agent": "coder",
                "status": "code_generated",  # use this so UI shows the code
                "content": f"Execution error: {error_summary}",
                "score": None,
                "iterations": iteration,
            })
            logger.warning("Code execution failed (job %s, iter %d): %s", job_id, iteration, stderr[:200])

        # ----------------------------------------------------------------
        # Build final_report from stdout (prose summary for answer card)
        # ----------------------------------------------------------------
        final_report = stdout.strip() if stdout.strip() else (
            f"Analysis complete. See chart for results."
            if chart_b64
            else "No output was produced. The code may need revision."
        )

        return {
            "code": code,
            "result": f"STDOUT:\n{stdout}\n\nSTDERR:\n{stderr}".strip(),
            "chart_b64": chart_b64,
            "final_report": final_report,
            "iteration": iteration,
            "messages": state.get("messages", []) + [
                {"role": "assistant", "content": f"Code:\n```python\n{code[:500]}\n```"}
            ],
        }

    except Exception as exc:
        logger.exception("Coder agent failed for job %s: %s", job_id, exc)
        await emit_error(job_id, "coder", str(exc))
        return {
            "code": "",
            "result": f"Coder agent error: {exc}",
            "chart_b64": "",
            "final_report": "",
            "iteration": iteration,
        }
