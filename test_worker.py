"""
test_worker.py — run from multi-agent-analysis/ root
Validates worker module structure without needing a live Redis.

Part A — Import + WorkerSettings validation (no services needed)
Part B — Full pipeline smoke test (needs GROQ_API_KEY + UPSTASH_REDIS_URL)
         Set RUN_FULL_TEST=1 in environment to enable Part B.

Usage:
    # Part A only (no keys needed):
    python test_worker.py

    # Full test (needs .env with all keys):
    RUN_FULL_TEST=1 python test_worker.py
"""

import asyncio
import inspect
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

# Stubs for missing env vars (Part A only)
os.environ.setdefault("GROQ_API_KEY", "dummy")
os.environ.setdefault("SUPABASE_URL", "https://dummy.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "dummy")
os.environ.setdefault("UPSTASH_REDIS_URL", "redis://localhost:6379")

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=True)

PASS = "\033[92m✔\033[0m"
FAIL = "\033[91m✘\033[0m"
SKIP = "\033[93m○\033[0m"


def check(label: str, condition: bool) -> None:
    icon = PASS if condition else FAIL
    print(f"  {icon}  {label}")
    if not condition:
        sys.exit(1)


def skip(label: str) -> None:
    print(f"  {SKIP}  SKIPPED: {label}")


def main() -> None:
    print("\n=== Worker Module Tests ===\n")

    # ----------------------------------------------------------------
    # PART A: Structure validation
    # ----------------------------------------------------------------
    print("[A] Import and structure validation")

    from backend.worker import WorkerSettings, run_analysis, enqueue_analysis

    check("WorkerSettings importable", True)
    check("run_analysis importable", callable(run_analysis))
    check("enqueue_analysis importable", callable(enqueue_analysis))

    # Validate WorkerSettings fields
    check("WorkerSettings.functions contains run_analysis",
          run_analysis in WorkerSettings.functions)
    check("WorkerSettings.job_timeout = 300",
          WorkerSettings.job_timeout == 300)
    check("WorkerSettings.max_tries = 2",
          WorkerSettings.max_tries == 2)
    check("WorkerSettings.redis_settings is set",
          WorkerSettings.redis_settings is not None)

    # Validate run_analysis signature
    sig = inspect.signature(run_analysis)
    params = list(sig.parameters.keys())
    print(f"  run_analysis params: {params}")
    for expected in ["ctx", "job_id", "question", "upload_id", "session_id", "df_schema", "df_json"]:
        check(f"param '{expected}' present", expected in params)

    # ----------------------------------------------------------------
    # PART B: Full pipeline smoke test
    # ----------------------------------------------------------------
    run_full = os.getenv("RUN_FULL_TEST", "0") == "1"

    print(f"\n[B] Full pipeline smoke test ({'ENABLED' if run_full else 'SKIPPED — set RUN_FULL_TEST=1'})")

    if not run_full:
        skip("Full pipeline requires GROQ_API_KEY + UPSTASH_REDIS_URL")
        print("\n\033[92m=== Part A passed! Set RUN_FULL_TEST=1 to run Part B. ===\033[0m\n")
        return

    # Only runs when RUN_FULL_TEST=1
    import uuid

    SAMPLE_ROWS = [
        {"PassengerId": i, "Survived": i % 2, "Pclass": (i % 3) + 1,
         "Age": 20.0 + i, "Fare": 10.0 * i}
        for i in range(1, 20)
    ]

    async def run_test():
        job_id = str(uuid.uuid4())
        ctx = {}  # ARQ context not needed for direct call

        print(f"\n  Running pipeline with job_id={job_id[:8]}...")
        result = await run_analysis(
            ctx=ctx,
            job_id=job_id,
            question="What is the average age of passengers by class?",
            upload_id="test-upload-id",
            session_id="test-session-id",
            df_schema=(
                "Columns: PassengerId (int64), Survived (int64), "
                "Pclass (int64), Age (float64), Fare (float64)\n"
                "Dtypes: PassengerId=int64, Survived=int64\n"
                "Sample rows:\n"
                "  PassengerId=1, Survived=1, Pclass=2, Age=21.0, Fare=10.0\n"
                "  PassengerId=2, Survived=0, Pclass=3, Age=22.0, Fare=20.0\n"
                "  PassengerId=3, Survived=1, Pclass=1, Age=23.0, Fare=30.0"
            ),
            df_json=json.dumps(SAMPLE_ROWS),
        )
        return result

    result = asyncio.run(run_test())

    print(f"\n  Result status:  {result.get('status')}")
    print(f"  Eval score:     {result.get('eval_score', 0):.2f}")
    print(f"  Iterations:     {result.get('iterations', 0)}")
    print(f"  Report snippet: {result.get('final_report', '')[:100]}")

    check("status is completed or failed", result.get("status") in ("completed", "failed"))
    if result.get("status") == "completed":
        check("eval_score present", "eval_score" in result)
        check("iterations present", "iterations" in result)

    print("\n\033[92m=== All worker tests passed! ===\033[0m\n")


if __name__ == "__main__":
    main()
