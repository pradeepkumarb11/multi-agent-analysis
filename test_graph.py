"""
test_graph.py — run from multi-agent-analysis/ root
Tests the LangGraph graph structure in two ways:

  Part A — Structural (no LLM, no Redis):
    Validates graph compiles, nodes are registered, topology is correct.

  Part B — Routing logic (no LLM, no Redis):
    Directly tests route_supervisor() with different state snapshots
    to verify the supervisor FSM is correct before a live run.

Usage:
    pip install langgraph python-dotenv
    python test_graph.py
    (No API keys needed for Part A and B)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

# Prevent graph.py from breaking if env vars absent (only needed at runtime)
os.environ.setdefault("GROQ_API_KEY", "dummy")
os.environ.setdefault("SUPABASE_URL", "https://dummy.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "dummy")
os.environ.setdefault("UPSTASH_REDIS_URL", "redis://localhost:6379")

from langgraph.graph import END
from backend.agents.supervisor import route_supervisor
from backend.state import AgentState

PASS = "\033[92m✔\033[0m"
FAIL = "\033[91m✘\033[0m"


def check(label: str, condition: bool) -> None:
    icon = PASS if condition else FAIL
    print(f"  {icon}  {label}")
    if not condition:
        sys.exit(1)


def make_state(**kwargs) -> AgentState:
    defaults: AgentState = {
        "messages": [], "question": "test?", "df_schema": "col1 (int)",
        "df_json": "[]", "upload_id": "u1", "session_id": "s1", "job_id": "",
        "plan": {}, "code": "", "result": "", "chart_b64": "",
        "critique": {}, "iteration": 0, "final_report": "",
    }
    defaults.update(kwargs)
    return defaults


def main() -> None:
    print("\n=== Graph Structure Tests ===\n")

    # ----------------------------------------------------------------
    # PART A: Compilation
    # ----------------------------------------------------------------
    print("[A] Graph compilation")
    try:
        from backend.graph import pipeline
        check("graph.py imports without error", True)
        check("pipeline object is not None", pipeline is not None)
        # LangGraph compiled graphs expose get_graph()
        g = pipeline.get_graph()
        node_names = set(g.nodes.keys())
        print(f"  Registered nodes: {node_names}")
        check("supervisor node registered", "supervisor" in node_names)
        check("planner node registered",    "planner"    in node_names)
        check("coder node registered",      "coder"      in node_names)
        check("critic node registered",     "critic"     in node_names)
    except Exception as e:
        check(f"graph compilation failed: {e}", False)

    # ----------------------------------------------------------------
    # PART B: Supervisor routing FSM
    # ----------------------------------------------------------------
    print("\n[B] Supervisor routing logic")

    # 1. No plan → planner
    route = route_supervisor(make_state())
    print(f"  no plan → '{route}'")
    check("no plan routes to planner", route == "planner")

    # 2. Plan exists, no code → coder
    route = route_supervisor(make_state(plan={"steps": ["step1", "step2"]}))
    print(f"  plan, no code → '{route}'")
    check("plan+no code routes to coder", route == "coder")

    # 3. Plan + code + critique approved → END
    route = route_supervisor(make_state(
        plan={"steps": ["s1"]}, code="print(1)",
        critique={"approved": True, "score": 0.9, "issues": []},
        iteration=1,
    ))
    print(f"  approved critique → '{route}'")
    check("approved routes to END", route == END)

    # 4. Plan + code + critique not approved, iter < 3 → coder
    route = route_supervisor(make_state(
        plan={"steps": ["s1"]}, code="print(1)",
        critique={"approved": False, "score": 0.5, "issues": ["fix this"]},
        iteration=1,
    ))
    print(f"  not approved, iter=1 → '{route}'")
    check("not approved iter<3 routes to coder", route == "coder")

    # 5. Iteration >= 3 → END (hard stop)
    route = route_supervisor(make_state(
        plan={"steps": ["s1"]}, code="print(1)",
        critique={"approved": False, "score": 0.4, "issues": ["still broken"]},
        iteration=3,
    ))
    print(f"  iter=3 hard stop → '{route}'")
    check("iter>=3 routes to END", route == END)

    print("\n\033[92m=== All graph tests passed! ===\033[0m\n")


if __name__ == "__main__":
    main()
