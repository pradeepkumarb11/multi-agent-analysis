"""
test_critic.py — run from multi-agent-analysis/ root
Tests the critic agent in isolation with 3 dummy scenarios:
  1. Good output  → should score high and approve
  2. Failed code  → should score low and reject (issues list)
  3. Iter limit   → should force approve regardless of score

Usage:
    1. Fill in .env with GROQ_API_KEY
    2. pip install langchain-groq pydantic python-dotenv
    3. python test_critic.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from backend.agents.critic import critic_node
from backend.state import AgentState

PASS = "\033[92m✔\033[0m"
FAIL = "\033[91m✘\033[0m"


def check(label: str, condition: bool) -> None:
    icon = PASS if condition else FAIL
    print(f"  {icon}  {label}")
    if not condition:
        sys.exit(1)


BASE_PLAN = {
    "steps": [
        "Group by Pclass and compute mean of Survived.",
        "Print survival rate per class.",
        "Create a bar chart of survival rate by class.",
        "Summarise findings.",
    ]
}

GOOD_CODE = """\
survival = df.groupby('Pclass')['Survived'].mean()
print(survival)
fig, ax = plt.subplots()
ax.bar(survival.index, survival.values, color='steelblue')
ax.set_xlabel('Passenger Class')
ax.set_ylabel('Survival Rate')
ax.set_title('Survival Rate by Class')
print('Class 1 had the highest survival rate.')
"""

GOOD_RESULT = """\
STDOUT:
Pclass
1    0.629630
2    0.472826
3    0.242363
Name: Survived, dtype: float64
Class 1 had the highest survival rate.

STDERR:
"""

BAD_CODE = """\
# forgot to group
print(df.head())
"""

BAD_RESULT = """\
STDOUT:
   PassengerId  Survived  Pclass   Age   Fare     Sex
0            1         0       3  22.0   7.25    male

STDERR:
"""

FAILED_CODE = """\
survival = df.groupby('Pclass')['NonExistentColumn'].mean()
print(survival)
"""

FAILED_RESULT = """\
STDOUT:

STDERR:
Traceback (most recent call last):
  File "tmp_code.py", line 1, in <module>
    survival = df.groupby('Pclass')['NonExistentColumn'].mean()
KeyError: 'NonExistentColumn'
"""


def make_state(code, result, iteration=1, **kwargs) -> AgentState:
    return {
        "messages": [],
        "question": "What is the survival rate by passenger class?",
        "df_schema": "Columns: PassengerId, Survived, Pclass, Age, Fare, Sex",
        "df_json": "[]",
        "upload_id": "test",
        "session_id": "test",
        "job_id": "",
        "plan": BASE_PLAN,
        "code": code,
        "result": result,
        "chart_b64": "",
        "critique": {},
        "iteration": iteration,
        "final_report": "",
        **kwargs,
    }


async def main() -> None:
    print("\n=== Critic Agent Tests ===\n")

    # ------------------------------------------------------------------
    # TEST 1: Good output — should get high score and approve
    # ------------------------------------------------------------------
    print("[1] Good output (expect: score >= 0.75, approved=True)")
    update = await critic_node(make_state(GOOD_CODE, GOOD_RESULT, iteration=1))
    c = update["critique"]

    print(f"\n  Scores — correctness: {c['correctness']:.2f}  "
          f"relevance: {c['relevance']:.2f}  "
          f"completeness: {c['completeness']:.2f}")
    print(f"  Final score: {c['score']:.2f}  |  Approved: {c['approved']}")
    print(f"  Issues: {c['issues']}")

    check("critique dict returned", "critique" in update)
    check("score is float", isinstance(c["score"], float))
    check("score between 0 and 1", 0.0 <= c["score"] <= 1.0)
    check("high score (>= 0.60) for good output", c["score"] >= 0.60)
    check("approved=True for good output", c["approved"] is True)

    # ------------------------------------------------------------------
    # TEST 2: Bad output — misses the question, no chart. Should reject.
    # ------------------------------------------------------------------
    print("\n[2] Irrelevant output (expect: low score, approved=False, issues non-empty)")
    update2 = await critic_node(make_state(BAD_CODE, BAD_RESULT, iteration=1))
    c2 = update2["critique"]

    print(f"\n  Scores — correctness: {c2['correctness']:.2f}  "
          f"relevance: {c2['relevance']:.2f}  "
          f"completeness: {c2['completeness']:.2f}")
    print(f"  Final score: {c2['score']:.2f}  |  Approved: {c2['approved']}")
    print(f"  Issues: {c2['issues']}")

    check("approved=False for bad output", c2["approved"] is False)
    check("issues list non-empty", len(c2["issues"]) > 0)

    # ------------------------------------------------------------------
    # TEST 3: Crashed code — correctness should be low
    # ------------------------------------------------------------------
    print("\n[3] Code with runtime error (expect: correctness low)")
    update3 = await critic_node(make_state(FAILED_CODE, FAILED_RESULT, iteration=1))
    c3 = update3["critique"]

    print(f"\n  Scores — correctness: {c3['correctness']:.2f}  "
          f"relevance: {c3['relevance']:.2f}  "
          f"completeness: {c3['completeness']:.2f}")
    print(f"  Final score: {c3['score']:.2f}  |  Approved: {c3['approved']}")

    check("correctness <= 0.5 for crashed code", c3["correctness"] <= 0.5)

    # ------------------------------------------------------------------
    # TEST 4: Iteration limit forces approval
    # ------------------------------------------------------------------
    print("\n[4] Iteration limit = 3 (expect: approved=True regardless of score)")
    update4 = await critic_node(make_state(BAD_CODE, BAD_RESULT, iteration=3))
    c4 = update4["critique"]

    print(f"\n  Score: {c4['score']:.2f}  |  Approved: {c4['approved']} (forced)")
    check("approved=True at iteration 3", c4["approved"] is True)

    print("\n\033[92m=== All critic tests passed! ===\033[0m\n")


if __name__ == "__main__":
    asyncio.run(main())
