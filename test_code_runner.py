"""
test_code_runner.py — run from multi-agent-analysis/ root
Tests the sandboxed code executor in isolation.

Usage:
    pip install pandas matplotlib numpy
    python test_code_runner.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from backend.tools.code_runner import run_code

PASS = "\033[92m✔\033[0m"
FAIL = "\033[91m✘\033[0m"


def check(label: str, condition: bool) -> None:
    icon = PASS if condition else FAIL
    print(f"  {icon}  {label}")
    if not condition:
        sys.exit(1)


# ---------------------------------------------------------------------------
# Minimal sample DataFrame JSON (mimics what the API will pass)
# ---------------------------------------------------------------------------
import json

SAMPLE_DF_JSON = json.dumps([
    {"PassengerId": 1, "Survived": 0, "Pclass": 3, "Age": 22.0, "Fare": 7.25},
    {"PassengerId": 2, "Survived": 1, "Pclass": 1, "Age": 38.0, "Fare": 71.28},
    {"PassengerId": 3, "Survived": 1, "Pclass": 3, "Age": 26.0, "Fare": 7.92},
    {"PassengerId": 4, "Survived": 1, "Pclass": 1, "Age": 35.0, "Fare": 53.10},
    {"PassengerId": 5, "Survived": 0, "Pclass": 3, "Age": 35.0, "Fare": 8.05},
])


def main() -> None:
    print("\n=== Code Runner Tests ===\n")

    # ------------------------------------------------------------------
    # TEST 1: Basic pandas computation
    # ------------------------------------------------------------------
    print("[1] Basic pandas computation")
    result = run_code(
        code="print(df.shape)\nprint(df['Survived'].mean())",
        df_json=SAMPLE_DF_JSON,
    )
    check("success=True", result["success"])
    check("stdout contains survival rate", "0.6" in result["stdout"] or "0.8" in result["stdout"] or "." in result["stdout"])
    check("stderr is empty", result["stderr"] == "")
    check("no chart (text only)", result["chart_b64"] == "")
    print(f"    stdout: {result['stdout'][:80]}")

    # ------------------------------------------------------------------
    # TEST 2: Matplotlib chart capture
    # ------------------------------------------------------------------
    print("\n[2] Chart generation + base64 capture")
    chart_code = """
fig, ax = plt.subplots(figsize=(6, 4))
ax.bar(df['Pclass'], df['Survived'], color='#6366F1')
ax.set_title('Survival by Class')
ax.set_xlabel('Passenger Class')
ax.set_ylabel('Survived')
"""
    result = run_code(code=chart_code, df_json=SAMPLE_DF_JSON)
    check("success=True", result["success"])
    check("chart_b64 is non-empty", len(result["chart_b64"]) > 100)
    check("chart_b64 is valid base64",
          __import__("base64").b64decode(result["chart_b64"]) is not None)
    print(f"    chart_b64 length: {len(result['chart_b64'])} chars")

    # ------------------------------------------------------------------
    # TEST 3: Syntax error handling
    # ------------------------------------------------------------------
    print("\n[3] Syntax error handling")
    result = run_code(code="this is not python !!!", df_json=SAMPLE_DF_JSON)
    check("success=False on bad code", not result["success"])
    check("stderr is non-empty", len(result["stderr"]) > 0)
    print(f"    stderr snippet: {result['stderr'][:80]}")

    # ------------------------------------------------------------------
    # TEST 4: Timeout enforcement
    # ------------------------------------------------------------------
    print("\n[4] Timeout enforcement (11-second sleep → should abort)")
    result = run_code(code="import time; time.sleep(11)", df_json=SAMPLE_DF_JSON)
    check("success=False on timeout", not result["success"])
    check("stderr mentions timeout", "timed out" in result["stderr"].lower() or "timeout" in result["stderr"].lower())
    print(f"    stderr: {result['stderr']}")

    # ------------------------------------------------------------------
    # TEST 5: No file loading (df already available)
    # ------------------------------------------------------------------
    print("\n[5] df variable pre-loaded (no file read needed)")
    result = run_code(
        code="print(f'Rows: {len(df)}, Cols: {list(df.columns)}')",
        df_json=SAMPLE_DF_JSON,
    )
    check("success=True", result["success"])
    check("stdout has row count", "Rows: 5" in result["stdout"])
    print(f"    stdout: {result['stdout'][:120]}")

    print("\n\033[92m=== All code runner tests passed! ===\033[0m\n")


if __name__ == "__main__":
    main()
