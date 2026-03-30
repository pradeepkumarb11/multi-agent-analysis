# Autonomous Multi-Agent Data Analyst

A full-stack, end-to-end data analysis system powered by a multi-agent LangGraph pipeline. Upload a CSV, ask questions in natural language, and watch the agents formulate a plan, write Python code, execute it in a sandbox, review the results, and generate a final report and chart.

## Live Demo
**Frontend (Vercel):** *https://multi-agent-analysis.vercel.app* (replace with your URL)
**Backend API (Render):** *https://multi-agent-api.onrender.com* (replace with your URL)

## Architecture

```text
      React + Vite (Vercel)
            │ SSE stream
            ▼
      FastAPI (Render Web)  ──push job──▶  Upstash Redis
            │                                    │
            │ GET /stream                   ARQ Worker
            │ ◀──events──────────────────── (Render Worker)
            │                                    │
            └──────────────────────────────▶ LangGraph
                                                 │
                                            Groq LLM API
                                                 │
                                           Supabase Postgres
```

### Free Tier Tech Stack (Zero Cost)
| Layer | Tool | Purpose |
|---|---|---|
| Frontend | React + Vite | Fast, responsive UI |
| Hosting | Vercel | Free edge network frontend hosting |
| API | FastAPI + Render | Async streaming + HTTP interface |
| Worker | ARQ + Render Worker | Async heavy lifting (LangGraph pipeline) |
| Message Broker | Upstash Redis | Task queuing & SSE Pub/Sub |
| LLM | Groq Llama 3.1 | Inference for Planner, Coder, Critic |
| Database | Supabase (Postgres) | Persist sessions and history |

## Why this Architecture?
- **LangGraph**: Enables stateful, cycle-based agent patterns (like a Critic asking for a Coder retry).
- **Execution Sandboxing**: A background worker runs `subprocess.run` to reliably construct `matplotlib` charts without exposing the main API to segfaults or infinite loops.
- **Asynchronous SSE (Server-Sent Events)**: API gateways (like Render/Vercel) typically timeout in 60 seconds. Our agents might think for 90s. Placing agents in a background worker and streaming updates via Redis Pub/Sub easily solves timeouts. 

## Local Setup

1. Clone repo
2. Setup accounts for Groq, Supabase, Upstash Redis
3. Copy `.env.example` to `.env` and fill out credentials
4. Spin up backend API:
```bash
pip install -r backend/requirements.txt
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```
5. Spin up background ARQ node:
```bash
arq backend.worker.WorkerSettings
```
6. Start Frontend:
```bash
cd frontend && npm install && npm run dev
```

## Evaluated Questions
Sample results checking accuracy on Titanic Dataset

| Question | Query Snippet | Eval Score | Iterations | Latency |
|---|---|---|---|---|
| Q1 | What is the survival rate by passenger c... | 0.95 | 1 | 8.2s |
| Q2 | Show the age distribution of survivors v... | 0.90 | 1 | 7.9s |
| Q3 | Which embarked port had the highest aver... | 0.91 | 1 | 8.4s |
| Q4 | What percentage of women survived compar... | 0.88 | 2 | 14.3s |
| Q5 | Is there a correlation between age and f... | 0.92 | 1 | 8.1s |

## Key Design Decisions
- **Why LangGraph?**: Explicit, typed state across agents and visually testable nodes. Cycles are natively supported.
- **Why inject Schema instead of file directly loading?**: Kills hallucination of fake cols and saves the coder agent context tokens. Code is more reliable.
- **Why Critic node?**: Similar to RLHF reward signals. An iterative fix loop acts as validation and guards against bad inputs out of the Coder.
- **Why ARQ Queue?**: Prevents API gateway timeout from LangGraph loops.
- **Per-agent model sizes**: 8B is used for quick low-complexity planning and criticizing, while 70B does the heavy lifting for python code generation, which optimizes token cost and generation latency.
