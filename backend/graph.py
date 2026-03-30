"""
backend/graph.py

LangGraph StateGraph — wires all 4 agent nodes into a runnable pipeline.

Graph topology:

    START
      │
      ▼
  supervisor ──────────────────────┐
      │                            │
      │ (conditional edge)         │ (loop back after critic)
      ├──→ planner ──→ supervisor  │
      │                            │
      ├──→ coder ──→ critic ───────┘
      │
      └──→ END

Flow walkthrough:
  1. START → supervisor (publishes "starting" event, decides "planner")
  2. supervisor → planner (generates Plan, publishes events)
  3. planner → supervisor (plan now in state, decides "coder")
  4. supervisor → coder (generates + executes code, publishes events)
  5. coder → critic (always: scores code output, publishes events)
  6. critic → supervisor (critique in state)
     → if approved or iter >= 3: supervisor → END
     → if not approved: supervisor → coder (retry with issues)

Compiled graph is a singleton — built once at module import and
reused across all worker task invocations (thread-safe for reads).
"""

import logging

from langgraph.graph import StateGraph, END

from backend.state import AgentState
from backend.agents.planner import planner_node
from backend.agents.coder import coder_node
from backend.agents.critic import critic_node
from backend.agents.supervisor import supervisor_node, route_supervisor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Graph builder — call once at startup
# ---------------------------------------------------------------------------


def build_graph():
    """
    Construct and compile the LangGraph StateGraph.

    Returns a compiled graph that can be invoked with:
        result = await graph.ainvoke(initial_state)

    The compiled graph is stateless — all state lives in AgentState dicts
    passed on each invocation. Safe to share across async tasks.
    """
    graph = StateGraph(AgentState)

    # ----------------------------------------------------------------
    # Register nodes
    # ----------------------------------------------------------------
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("planner",    planner_node)
    graph.add_node("coder",      coder_node)
    graph.add_node("critic",     critic_node)

    # ----------------------------------------------------------------
    # Entry point — always start at supervisor
    # ----------------------------------------------------------------
    graph.set_entry_point("supervisor")

    # ----------------------------------------------------------------
    # Conditional edges FROM supervisor
    # supervisor_node runs first (publishes event),
    # then route_supervisor(state) is called to decide direction
    # ----------------------------------------------------------------
    graph.add_conditional_edges(
        "supervisor",
        route_supervisor,
        {
            "planner": "planner",
            "coder":   "coder",
            END:       END,
        },
    )

    # ----------------------------------------------------------------
    # Fixed edges
    # planner always returns to supervisor (may then go to coder)
    # coder always goes to critic (never directly to END)
    # critic always returns to supervisor (decides approve or retry)
    # ----------------------------------------------------------------
    graph.add_edge("planner", "supervisor")
    graph.add_edge("coder",   "critic")
    graph.add_edge("critic",  "supervisor")

    compiled = graph.compile()
    logger.info("LangGraph pipeline compiled successfully.")
    return compiled


# ---------------------------------------------------------------------------
# Singleton compiled graph — imported by worker.py
# ---------------------------------------------------------------------------

pipeline = build_graph()
