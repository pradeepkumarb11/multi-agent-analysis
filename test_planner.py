"""
test_planner.py — run from multi-agent-analysis/ root
Tests the planner agent in isolation (no Redis, no graph).

Usage:
    1. Fill in .env with GROQ_API_KEY
    2. pip install langchain-groq langgraph pydantic python-dotenv
    3. python test_planner.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from backend.agents.planner import planner_node
from backend.state import AgentState

PASS = "\033[92m✔\033[0m"
FAIL = "\033[91m✘\033[0m"


def check(label: str, condition: bool) -> None:
    icon = PASS if condition else FAIL
    print(f"  {icon}  {label}")
    if not condition:
        sys.exit(1)


# ---------------------------------------------------------------------------
# Minimal state — no Redis in test (job_id="" suppresses publish errors)
# ---------------------------------------------------------------------------
TEST_STATE: AgentState = {
    "messages": [],
    "question": "What is the survival rate by passenger class?",
    "df_schema": (
        "Columns: PassengerId (int64), Survived (int64), Pclass (int64), "
        "Name (object), Sex (object), Age (float64), Fare (float64)\n"
        "Sample rows:\n"
        "  PassengerId=1, Survived=0, Pclass=3, Name='Braund, Mr. Owen Harris', "
        "Sex='male', Age=22.0, Fare=7.25\n"
        "  PassengerId=2, Survived=1, Pclass=1, Name='Cumings, Mrs. John Bradley', "
        "Sex='female', Age=38.0, Fare=71.28\n"
        "  PassengerId=3, Survived=1, Pclass=3, Name='Heikkinen, Miss. Laina', "
        "Sex='female', Age=26.0, Fare=7.92"
    ),
    "df_json": "[]",
    "upload_id": "test-upload-id",
    "session_id": "test-session-id",
    "job_id": "",  # empty → Redis publish is a no-op (will log error, not crash)
    "plan": {},
    "code": "",
    "result": "",
    "chart_b64": "",
    "critique": {},
    "iteration": 0,
    "final_report": "",
}


async def main() -> None:
    print("\n=== Planner Agent Test ===\n")

    print("[1] Invoking planner_node with Titanic survival question...")
    update = await planner_node(TEST_STATE)

    print(f"\n  Raw update keys: {list(update.keys())}")

    check("update contains 'plan' key", "plan" in update)
    plan = update["plan"]
    check("plan is a dict", isinstance(plan, dict))
    check("plan has 'steps' key", "steps" in plan)
    check("steps is a list", isinstance(plan["steps"], list))
    check("steps is non-empty", len(plan["steps"]) > 0)
    check("at least 3 steps", len(plan["steps"]) >= 3)

    print(f"\n  Steps produced ({len(plan['steps'])}):")
    for i, step in enumerate(plan["steps"], 1):
        print(f"    {i}. {step}")

    check("messages updated", "messages" in update)
    check("messages list non-empty", len(update["messages"]) > 0)

    print("\n\033[92m=== Planner test passed! ===\033[0m\n")


if __name__ == "__main__":
    asyncio.run(main())
