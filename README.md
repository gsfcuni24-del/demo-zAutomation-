# zAutomation Helper AI

Multi-agent AI platform that ingests industrial PLC/HMI data (Excel IO lists, Siemens TIA XML, Rockwell `.L5X`), normalizes it into a **Universal Intermediate Representation (UIR)**, lets engineers modify it in natural language, and exports vendor-native files with visual diffs.

> Status: **Phase 1 — Foundation** (project skeleton, dependencies, config, local Docker stack).

## Repository layout

```
.
├── docker-compose.yml          # postgres, redis, qdrant, api, worker, web
├── .env.example                # copy to .env
├── backend/                    # FastAPI · Python 3.12 · uv
│   ├── pyproject.toml / uv.lock
│   ├── app/
│   │   ├── main.py             # FastAPI app factory
│   │   ├── core/config.py      # Pydantic Settings (development / staging / production)
│   │   ├── core/logging.py     # structlog
│   │   ├── api/v1/             # versioned routers (health, readiness)
│   │   ├── db/session.py       # async SQLAlchemy/SQLModel engine
│   │   ├── models/             # SQLModel tables            (Phase 2)
│   │   ├── schemas/uir/        # UIR Pydantic models        (Phase 2)
│   │   ├── services/           # storage, diff engine       (Phase 3)
│   │   ├── parsers/            # Siemens TIA / Rockwell     (Phase 3)
│   │   ├── compilers/          # Jinja2 vendor compilers    (Phase 3, Agent 6, non-LLM)
│   │   ├── safety/             # networkx rule engine       (Phase 4, Agent 5, non-LLM)
│   │   ├── agents/             # LLM agents 1-4             (Phase 5)
│   │   ├── orchestration/      # LangGraph DAG              (Phase 5)
│   │   └── workers/            # ARQ background worker
│   └── tests/
└── frontend/                   # Next.js 15 (App Router) · TypeScript · Tailwind · shadcn/ui
    ├── package.json / package-lock.json
    └── src/{app,components/ui,lib,stores,hooks,types}
```

## Run locally (Docker — recommended)

Prerequisites: Docker with Compose v2.

```bash
cp .env.example .env          # add OPENAI_API_KEY / ANTHROPIC_API_KEY when you reach Phase 5
docker compose up -d --build
```

| Service  | URL                                          |
|----------|----------------------------------------------|
| Web UI   | http://localhost:3000                        |
| API docs | http://localhost:8000/docs                   |
| Health   | http://localhost:8000/api/v1/health          |
| Ready    | http://localhost:8000/api/v1/health/ready    |
| Qdrant   | http://localhost:6333/dashboard              |

Source directories are bind-mounted, so the API, worker and web UI hot-reload when you edit code. On start, containers run `uv sync` / `npm install` so dependency changes are picked up after `docker compose up -d --build`. All ports are bound to `127.0.0.1` only.

```bash
docker compose logs -f api              # tail logs
docker compose exec api pytest          # run backend tests in the container
docker compose down                     # stop (add -v to drop data volumes)
```

## Run without Docker

Infrastructure only: `docker compose up -d postgres redis qdrant`, then set `POSTGRES_HOST=localhost`, `REDIS_URL=redis://localhost:6379/0`, `QDRANT_URL=http://localhost:6333` in `.env`.

**Backend** (requires [uv](https://docs.astral.sh/uv/)):

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload            # API on :8000
uv run arq app.workers.settings.WorkerSettings  # worker
uv run pytest && uv run ruff check . && uv run mypy app tests
```

**Frontend** (Node 22):

```bash
cd frontend
npm ci
npm run dev                                     # UI on :3000
npm run lint && npm run typecheck && npm run build
```

## Production frontend image

`NEXT_PUBLIC_*` variables are inlined at build time, so pass the public API URL when building:

```bash
docker build --target prod \
  --build-arg NEXT_PUBLIC_API_URL=https://api.example.com \
  --build-arg NEXT_PUBLIC_WS_URL=wss://api.example.com \
  -t zautomation-web ./frontend
```

## Configuration

All settings live in `backend/app/core/config.py` and are loaded from environment variables / `.env`.

- `ENVIRONMENT` = `development` | `staging` | `production`.
- In staging/production the app refuses to start with the default `SECRET_KEY` or `POSTGRES_PASSWORD`; production also forbids `DEBUG=true` and `DB_ECHO=true`.
- Per-agent LLM models can be overridden with nested env vars, e.g. `LLM__LOGIC_DRAFTER=anthropic/claude-3-5-sonnet-20241022`.
