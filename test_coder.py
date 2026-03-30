"""
test_coder.py — run from multi-agent-analysis/ root
Tests the coder agent in isolation:
  - Generates code from a real Groq LLM call
  - Executes it via code_runner (subprocess)
  - Checks stdout, chart capture, and retry injection

Usage:
    1. Fill in .env with GROQ_API_KEY
    2. pip install langchain-groq pandas matplotlib numpy python-dotenv
    3. python test_coder.py
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from backend.agents.coder import coder_node
from backend.state import AgentState

PASS = "\033[92m✔\033[0m"
FAIL = "\033[91m✘\033[0m"


def check(label: str, condition: bool) -> None:
    icon = PASS if condition else FAIL
    print(f"  {icon}  {label}")
    if not condition:
        sys.exit(1)


# ---------------------------------------------------------------------------
# Sample Titanic-like data
# ---------------------------------------------------------------------------
SAMPLE_ROWS = [
    {"PassengerId": i, "Survived": i % 2, "Pclass": (i % 3) + 1,
     "Age": 20.0 + i, "Fare": 10.0 * i, "Sex": "male" if i % 2 == 0 else "female"}
    for i in range(1, 51)
]
DF_JSON = json.dumps(SAMPLE_ROWS)

DF_SCHEMA = (
    "Columns: PassengerId (int64), Survived (int64), Pclass (int64), "
    "Age (float64), Fare (float64), Sex (object)\n"
    "Dtypes: PassengerId=int64, Survived=int64, Pclass=int64, Age=float64, "
    "Fare=float64, Sex=object\n"
    "Sample rows:\n"
    "  PassengerId=1, Survived=1, Pclass=2, Age=21.0, Fare=10.0, Sex=female\n"
    "  PassengerId=2, Survived=0, Pclass=3, Age=22.0, Fare=20.0, Sex=male\n"
    "  PassengerId=3, Survived=1, Pclass=1, Age=23.0, Fare=30.0, Sex=female"
)

BASE_STATE: AgentState = {
    "messages": [],
    "question": "What is the survival rate by passenger class?",
    "df_schema": DF_SCHEMA,
    "df_json": DF_JSON,
    "upload_id": "test-upload",
    "session_id": "test-session",
    "job_id": "",        # no Redis in test
    "plan": {
        "steps": [
            "Group the dataframe by Pclass and compute the mean of Survived.",
            "Print the survival rate per class.",
            "Create a bar chart of survival rate by class.",
            "Summarise findings in plain English.",
        ]
    },
    "code": "",
    "result": "",
    "chart_b64": "",
    "critique": {},
    "iteration": 0,
    "final_report": "",
}


async def main() -> None:
    print("\n=== Coder Agent Tests ===\n")

    # ------------------------------------------------------------------
    # TEST 1: Fresh run (iteration 0 → 1)
    # ------------------------------------------------------------------
    print("[1] First attempt — generates + executes code")
    update = await coder_node({**BASE_STATE})

    print(f"\n  Code snippet (first 300 chars):")
    print("  " + update.get("code", "")[:300].replace("\n", "\n  "))

    check("update has 'code' key", "code" in update)
    check("code is non-empty string", len(update.get("code", "")) > 10)
    check("iteration incremented to 1", update.get("iteration") == 1)
    check("result captured", len(update.get("result", "")) > 0)
    check("messages updated", len(update.get("messages", [])) > 0)

    print(f"\n  Result (stdout):")
    print("  " + update.get("result", "")[:300].replace("\n", "\n  "))

    has_chart = len(update.get("chart_b64", "")) > 100
    print(f"\n  Chart captured: {'YES (' + str(len(update['chart_b64'])) + ' chars)' if has_chart else 'NO (text-only output)'}")

    # ------------------------------------------------------------------
    # TEST 2: Retry with critique issues
    # ------------------------------------------------------------------
    print("\n[2] Retry with injected critique issues")
    retry_state = {
        **BASE_STATE,
        "iteration": 1,
        "code": update.get("code", ""),
        "result": update.get("result", ""),
        "critique": {
            "score": 0.5,
            "issues": [
                "Survival rate was not printed — missing print() call.",
                "Chart label is missing — add axis labels.",
            ],
            "approved": False,
        },
    }
    retry_update = await coder_node(retry_state)

    check("iteration incremented to 2", retry_update.get("iteration") == 2)
    check("new code generated", len(retry_update.get("code", "")) > 10)
    print(f"\n  Retry code snippet:")
    print("  " + retry_update.get("code", "")[:200].replace("\n", "\n  "))

    print("\n\033[92m=== Coder agent tests passed! ===\033[0m\n")


if __name__ == "__main__":
    asyncio.run(main())
