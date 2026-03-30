"""
eval.py

Runs 5 analytical questions automatically against the running backend API.
Verifies logic correctness, iteration count, latency, and outputs a table.
"""

import os
import sys
import time
import json
import httpx
from tabulate import tabulate

BASE_URL = os.getenv("API_URL", "http://localhost:8000")
CSV_PATH = "titanic.csv"
CSV_URL = "https://raw.githubusercontent.com/datasciencedojo/datasets/master/titanic.csv"

QUESTIONS = [
    "What is the survival rate by passenger class?",
    "Show the age distribution of survivors vs non-survivors",
    "Which embarked port had the highest average fare?",
    "What percentage of women survived compared to men?",
    "Is there a correlation between age and fare paid?"
]

def download_titanic():
    if not os.path.exists(CSV_PATH):
        print(f"Downloading {CSV_PATH}...")
        r = httpx.get(CSV_URL)
        r.raise_for_status()
        with open(CSV_PATH, "wb") as f:
            f.write(r.content)

def run_eval():
    download_titanic()
    
    with httpx.Client(base_url=BASE_URL, timeout=120) as client:
        # Create session
        res = client.post("/api/sessions")
        res.raise_for_status()
        session_id = res.json()["session_id"]
        
        # Upload CSV
        with open(CSV_PATH, "rb") as f:
            res = client.post(
                f"/api/upload/{session_id}",
                files={"file": (CSV_PATH, f, "text/csv")}
            )
            res.raise_for_status()
            upload_id = res.json()["upload_id"]
            
        results = []
        
        # Evaluation multi-agent system.
        
        print("\nRunning Evaluation...\n")
        
        for idx, q in enumerate(QUESTIONS, 1):
            print(f"Q{idx}: {q}")
            t0 = time.time()
            res = client.post(
                f"/api/ask/{session_id}",
                json={"question": q, "upload_id": upload_id}
            )
            job_id = res.json().get("job_id")
            
            # Use streaming endpoint to wait for end event
            score = 0
            iters = 0
            
            with httpx.stream("GET", f"{BASE_URL}/api/stream/{job_id}", timeout=300) as stream:
                for line in stream.iter_lines():
                    if line.startswith("data:"):
                        data = json.loads(line[5:])
                        if data.get("agent") == "END":
                            score = data.get("eval_score", 0.0)
                            iters = data.get("iterations", 0)
                            break
                            
            latency = time.time() - t0
            
            results.append([
                f"Q{idx}",
                q[:40] + "...",
                f"{score:.2f}",
                iters,
                f"{latency:.1f}s"
            ])
            print(f"   Done in {latency:.1f}s, Score={score:.2f}, Iters={iters}")
    
    # Save & Print Results
    headers = ["Question", "Query Snippet", "Eval Score", "Iterations", "Latency"]
    print("\n" + tabulate(results, headers=headers, tablefmt="grid"))
    
    import csv
    with open("eval_results.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(results)
    
    print("\nResults saved to eval_results.csv")

if __name__ == "__main__":
    run_eval()
