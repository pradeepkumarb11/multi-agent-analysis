"""
test_api.py — run from multi-agent-analysis/ root
Smoke-tests all FastAPI endpoints against a running local server.

Prerequisites:
  1. Fill in .env
  2. Run: uvicorn backend.main:app --port 8000 (in a separate terminal)
  3. Run: python test_api.py

Does NOT test SSE streaming (use test_worker.py with RUN_FULL_TEST=1 for that).
"""

import json
import os
import sys
import time

import httpx

BASE_URL = os.getenv("API_URL", "http://localhost:8000")
CSV_PATH = os.getenv("CSV_PATH", "titanic.csv")

PASS = "\033[92m✔\033[0m"
FAIL = "\033[91m✘\033[0m"


def check(label: str, condition: bool) -> None:
    icon = PASS if condition else FAIL
    print(f"  {icon}  {label}")
    if not condition:
        sys.exit(1)


def main() -> None:
    print(f"\n=== API Smoke Tests against {BASE_URL} ===\n")

    with httpx.Client(base_url=BASE_URL, timeout=30) as client:

        # ----------------------------------------------------------------
        # 1. Health check
        # ----------------------------------------------------------------
        print("[1] GET /api/health")
        r = client.get("/api/health")
        check("status 200", r.status_code == 200)
        data = r.json()
        check("status=ok", data.get("status") == "ok")
        check("model field present", "model" in data)
        print(f"  response: {data}")

        # ----------------------------------------------------------------
        # 2. Create session
        # ----------------------------------------------------------------
        print("\n[2] POST /api/sessions")
        r = client.post("/api/sessions")
        check("status 200", r.status_code == 200)
        session_id = r.json()["session_id"]
        check("session_id is UUID string", len(session_id) == 36)
        print(f"  session_id: {session_id}")

        # ----------------------------------------------------------------
        # 3. Upload CSV
        # ----------------------------------------------------------------
        print("\n[3] POST /api/upload/{session_id}")

        # Generate a tiny CSV inline if titanic.csv is not present
        if not os.path.exists(CSV_PATH):
            print(f"  {CSV_PATH} not found — using inline test CSV")
            csv_bytes = (
                b"PassengerId,Survived,Pclass,Age,Fare,Sex\n"
                b"1,0,3,22.0,7.25,male\n"
                b"2,1,1,38.0,71.28,female\n"
                b"3,1,3,26.0,7.92,female\n"
                b"4,1,1,35.0,53.10,female\n"
                b"5,0,3,35.0,8.05,male\n"
            )
            csv_name = "test.csv"
        else:
            with open(CSV_PATH, "rb") as f:
                csv_bytes = f.read()
            csv_name = os.path.basename(CSV_PATH)

        r = client.post(
            f"/api/upload/{session_id}",
            files={"file": (csv_name, csv_bytes, "text/csv")},
        )
        check("status 200", r.status_code == 200)
        upload_data = r.json()
        upload_id = upload_data["upload_id"]
        check("upload_id present", len(upload_id) == 36)
        check("row_count > 0", upload_data["row_count"] > 0)
        check("columns list non-empty", len(upload_data["columns"]) > 0)
        print(f"  upload_id: {upload_id}")
        print(f"  rows: {upload_data['row_count']}  cols: {upload_data['col_count']}")
        print(f"  columns: {upload_data['columns'][:5]}")

        # ----------------------------------------------------------------
        # 4. Ask a question → get job_id
        # ----------------------------------------------------------------
        print("\n[4] POST /api/ask/{session_id}")
        r = client.post(
            f"/api/ask/{session_id}",
            json={"question": "What is the survival rate?", "upload_id": upload_id},
        )
        check("status 200", r.status_code == 200)
        job_id = r.json()["job_id"]
        check("job_id is UUID", len(job_id) == 36)
        print(f"  job_id: {job_id}")
        print(f"  (Worker will now process this job asynchronously)")

        # ----------------------------------------------------------------
        # 5. History (should be empty before worker completes)
        # ----------------------------------------------------------------
        print("\n[5] GET /api/history/{session_id}")
        r = client.get(f"/api/history/{session_id}")
        check("status 200", r.status_code == 200)
        hist = r.json()
        check("session_id matches", hist["session_id"] == session_id)
        check("messages is list", isinstance(hist["messages"], list))
        print(f"  message count (before worker): {hist['count']}")

        # ----------------------------------------------------------------
        # 6. Invalid upload (non-CSV)
        # ----------------------------------------------------------------
        print("\n[6] POST /api/upload — invalid file type")
        r = client.post(
            f"/api/upload/{session_id}",
            files={"file": ("test.json", b'{"key": "value"}', "application/json")},
        )
        check("status 400 for non-CSV", r.status_code == 400)
        print(f"  error: {r.json()['detail']}")

    print("\n\033[92m=== All API smoke tests passed! ===\033[0m\n")
    print("Next: Open GET /api/stream/{job_id} in a browser or run:")
    print(f"  curl -N {BASE_URL}/api/stream/{job_id}\n")


if __name__ == "__main__":
    main()
