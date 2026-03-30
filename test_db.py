"""
test_db.py  — run from multi-agent-analysis/ root
Tests Supabase connectivity: inserts a session, uploads row,
message row, reads them back, then verifies ping().

Usage:
  1.  Create .env in multi-agent-analysis/ from .env.example
  2.  pip install supabase python-dotenv
  3.  python test_db.py
"""

import sys
import os

# Load .env from the project root
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# Make sure backend/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.db.supabase_client import (
    ping,
    insert_session,
    get_session,
    insert_upload,
    get_upload,
    insert_message,
    get_messages,
)

PASS = "\033[92m✔\033[0m"
FAIL = "\033[91m✘\033[0m"


def check(label: str, condition: bool) -> None:
    icon = PASS if condition else FAIL
    print(f"  {icon}  {label}")
    if not condition:
        sys.exit(1)


def main() -> None:
    print("\n=== Supabase Connection Test ===\n")

    # 1. Ping
    print("[1] Connectivity ping")
    result = ping()
    check("ping() returned True", result)

    # 2. Insert session
    print("\n[2] Session table")
    session = insert_session(user_agent="test-runner/1.0")
    check("session row returned", bool(session))
    check("session has id", "id" in session)
    sid = session["id"]
    print(f"    session_id = {sid}")

    # 3. Read session back
    fetched = get_session(sid)
    check("get_session() returned row", fetched is not None)
    check("session ids match", fetched["id"] == sid)

    # 4. Insert upload
    print("\n[3] Uploads table")
    upload = insert_upload(
        session_id=sid,
        filename="titanic.csv",
        row_count=891,
        col_names=["PassengerId", "Survived", "Pclass", "Name", "Age"],
        dtypes={"PassengerId": "int64", "Survived": "int64", "Age": "float64"},
        sample_rows=[
            {"PassengerId": 1, "Survived": 0, "Pclass": 3, "Age": 22.0},
            {"PassengerId": 2, "Survived": 1, "Pclass": 1, "Age": 38.0},
        ],
    )
    check("upload row returned", bool(upload))
    uid = upload["id"]
    print(f"    upload_id = {uid}")

    fetched_upload = get_upload(uid)
    check("get_upload() returned row", fetched_upload is not None)
    check("upload filename matches", fetched_upload["filename"] == "titanic.csv")

    # 5. Insert message
    print("\n[4] Messages table")
    message = insert_message(
        session_id=sid,
        upload_id=uid,
        question="Test question?",
        final_report="Test report.",
        chart_b64="",
        eval_score=0.95,
        iterations=1,
    )
    check("message row returned", bool(message))
    mid = message["id"]
    print(f"    message_id = {mid}")

    # 6. Read history
    history = get_messages(sid)
    check("get_messages() returns list", isinstance(history, list))
    check("history contains 1 item", len(history) == 1)
    check("question matches", history[0]["question"] == "Test question?")

    print("\n\033[92m=== All checks passed! Supabase is connected correctly. ===\033[0m\n")


if __name__ == "__main__":
    main()
