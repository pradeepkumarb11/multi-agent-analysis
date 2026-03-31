#!/bin/bash
set -e

echo "============================================="
echo " Starting Multi-Agent System (Free Tier Mode)"
echo "============================================="

# 1. Start the ARQ background worker as a detached process (&)
echo "Booting ARQ Worker in the background..."
arq backend.worker.WorkerSettings &
WORKER_PID=$!

# 2. Start the FastAPI web server in the foreground
echo "Booting FastAPI server..."
uvicorn backend.main:app --host 0.0.0.0 --port $PORT

# If FastAPI crashes or terminates, make sure we clean up the worker
kill $WORKER_PID
