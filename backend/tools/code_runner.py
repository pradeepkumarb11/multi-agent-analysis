"""
backend/tools/code_runner.py

Safely executes LLM-generated Python code in an isolated subprocess.

Design decisions:
- NEVER uses eval() or exec() in the main process — security boundary.
- Writes code to a temp .py file, runs it via subprocess.
- 10-second hard timeout via subprocess.run(timeout=...).
- Injects standard imports at the top so the LLM never has to.
- Captures matplotlib figures as base64 PNG via a post-exec snippet.
- Returns a typed dict: { stdout, stderr, chart_b64, success }.
"""

import base64
import json
import logging
import os
import subprocess
import sys
import tempfile
import textwrap
from typing import TypedDict

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 10

# ---------------------------------------------------------------------------
# Preamble injected at the top of every LLM-generated script
# ---------------------------------------------------------------------------
_PREAMBLE = textwrap.dedent("""\
    import pandas as pd
    import numpy as np
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import io, base64, json, warnings
    warnings.filterwarnings('ignore')

    # 'df' will be injected via the runner wrapper below
""")

# ---------------------------------------------------------------------------
# Postamble: after user code runs, capture any open matplotlib figures
# ---------------------------------------------------------------------------
_POSTAMBLE = textwrap.dedent("""\

    # --- chart capture (injected by code_runner) ---
    _chart_b64 = ""
    _fig_nums = plt.get_fignums()
    if _fig_nums:
        _buf = io.BytesIO()
        plt.savefig(_buf, format='png', dpi=120,
                    bbox_inches='tight', facecolor='#1A1A1A')
        _buf.seek(0)
        _chart_b64 = base64.b64encode(_buf.read()).decode('utf-8')
        plt.close('all')

    # Emit structured JSON footer so the runner can parse it cleanly
    print("\\n__RUNNER_OUTPUT__")
    print(json.dumps({"chart_b64": _chart_b64}))
""")


class RunResult(TypedDict):
    stdout: str
    stderr: str
    chart_b64: str
    success: bool


def run_code(code: str, df_json: str = "") -> RunResult:
    """
    Execute LLM-generated code in a sandboxed subprocess.

    Parameters
    ----------
    code    : str — raw Python code from the LLM (no preamble needed)
    df_json : str — JSON-serialised DataFrame (from df.to_json(orient='records'))
                    If provided, the DataFrame is loaded as 'df' inside the script.

    Returns
    -------
    RunResult TypedDict with stdout, stderr, chart_b64, success.
    """
    # ------------------------------------------------------------------
    # Build the complete script to execute
    # ------------------------------------------------------------------
    df_injection = ""
    if df_json:
        # Safely pass the DataFrame via a JSON literal embedded in code
        escaped = df_json.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
        df_injection = textwrap.dedent(f"""\
            import pandas as pd, json as _json
            df = pd.DataFrame(_json.loads(\"\"\"{escaped}\"\"\"))
        """)

    full_script = "\n".join([_PREAMBLE, df_injection, code, _POSTAMBLE])

    # ------------------------------------------------------------------
    # Write to a temp file — never exec() in-process
    # ------------------------------------------------------------------
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            delete=False,
            encoding="utf-8",
        ) as tmp:
            tmp.write(full_script)
            tmp_path = tmp.name

        logger.debug("Executing temp script: %s", tmp_path)

        # ------------------------------------------------------------------
        # Run in subprocess with hard timeout
        # ------------------------------------------------------------------
        proc = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )

        raw_stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        success = proc.returncode == 0

        # ------------------------------------------------------------------
        # Parse structured footer from stdout
        # ------------------------------------------------------------------
        chart_b64 = ""
        clean_stdout = raw_stdout

        marker = "__RUNNER_OUTPUT__"
        if marker in raw_stdout:
            parts = raw_stdout.split(marker, 1)
            clean_stdout = parts[0].rstrip()
            try:
                meta = json.loads(parts[1].strip())
                chart_b64 = meta.get("chart_b64", "")
            except json.JSONDecodeError:
                logger.warning("Could not parse runner footer JSON.")

        if stderr and not success:
            logger.warning("Code execution error:\n%s", stderr)

        return RunResult(
            stdout=clean_stdout,
            stderr=stderr,
            chart_b64=chart_b64,
            success=success,
        )

    except subprocess.TimeoutExpired:
        logger.error("Code execution timed out after %ds", TIMEOUT_SECONDS)
        return RunResult(
            stdout="",
            stderr=f"Execution timed out after {TIMEOUT_SECONDS} seconds.",
            chart_b64="",
            success=False,
        )
    except Exception as exc:
        logger.exception("Unexpected error in code runner: %s", exc)
        return RunResult(
            stdout="",
            stderr=f"Runner internal error: {exc}",
            chart_b64="",
            success=False,
        )
    finally:
        # Always clean up the temp file
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
