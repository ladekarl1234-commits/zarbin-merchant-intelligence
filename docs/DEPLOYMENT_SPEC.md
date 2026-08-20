# Deployment Specification

Two deployment shapes: the **challenge/local** shape (what a judge runs today) and the
**production-shaped** target (multi-tenant). Capacity numbers are only given where measured.

---

## 1. Challenge / local deployment

### Dependencies
- Python ≥ 3.11 with **[uv](https://docs.astral.sh/uv/)** (manages the venv + lock).
- Node ≥ 20 (only to rebuild the frontend; a prebuilt `zarin/static` is committed).
- The challenge dataset at `data/other_challenge_data.csv.gz` (or `ZARIN_DATA_PATH`).
- Runtime Python deps: `duckdb`, `fastapi`, `uvicorn` (no AI/GA4 SDKs — the AI layer uses stdlib).

### Commands
```bash
# 1) run everything (builds Parquet marts on first run, then serves)
uv run zarin
#    → http://localhost:8630   (Merchant + Control Center share this URL)

# rebuild marts explicitly
uv run python -m zarin.pipeline
# rebuild the frontend (outputs to zarin/static)
cd frontend && npm ci && npm run build
# tests / lint / copilot eval
uv run pytest -q ; uv run ruff check . ; uv run python -m zarin.ai.eval
```
Windows on OneDrive: set `UV_LINK_MODE=copy` (hardlinks are blocked). Launchers in
`scripts/run.ps1|cmd|sh` set this for you; VS Code task "Run Zarbin Dashboard" wraps `uv run zarin`.

### Ports / URLs
- API + SPA: `http://localhost:8630` (host `127.0.0.1`; `ZARIN_HOST=0.0.0.0` in containers).
- Merchant Workspace: `/#/overview`. Control Center: `/#/ops/overview` (or the "مرکز کنترل" switch).
- OpenAPI: `/api/docs`.

### Environment
| Var | Default | Purpose |
|---|---|---|
| `ZARIN_PORT` | `8630` | server port |
| `ZARIN_HOST` | `127.0.0.1` | bind host |
| `ZARIN_DATA_PATH` | `data/other_challenge_data.csv.gz` | source CSV |
| `ZARIN_MARTS_DIR` | `data/marts` | Parquet marts |
| `ZARIN_TELEMETRY_DIR` | `data/telemetry` | JSONL telemetry |
| `OPENROUTER_API_KEY` | — | optional; enables LLM rephrasing |
| `OPENROUTER_MODEL` | `deepseek/deepseek-chat-v3-0324:free` | policy-enforced free model |
| `GA4_PROPERTY_ID`, `GOOGLE_APPLICATION_CREDENTIALS` | — | optional GA4 source |

Secrets come only from the environment; none are committed. The dataset is git-ignored and is
not in history.

### Docker
`docker compose up` builds the image, builds marts, and serves on `8630` (`ZARIN_HOST=0.0.0.0`).
Measured local perf: pipeline build ~33s; warm API responses < 0.7s on the largest merchant.

---

## 2. Production-shaped deployment (multi-tenant target)

This is the *target*, not what ships in the challenge. Rationale and triggers: `docs/ADR/0001`.

| Concern | Hackathon (today) | Production target |
|---|---|---|
| Frontend | committed `zarin/static`, served by FastAPI | CDN static hosting; same build |
| API | single uvicorn process | uvicorn/gunicorn workers behind a load balancer, horizontally scaled |
| Analytics storage | local DuckDB over Parquet | object storage (S3/GCS) for raw + marts; **ClickHouse**/managed OLAP when row-count/concurrency demand |
| Control-plane storage | JSONL + in-memory rings | **PostgreSQL** (tenants, users, feedback, telemetry, audit) |
| Ingestion | one deterministic build | **queue + workers** behind `DataSourceAdapter`; scheduled/backfill refresh |
| Caching | `lru_cache` + in-memory | **Redis** *only if* a measured hit-rate need appears |
| Observability | `obs.py` / `ai/telemetry.py` JSONL | **OpenTelemetry** traces/metrics/logs + durable backend |
| Secrets | env vars | secret manager (Vault/cloud KMS) |
| AuthN | none (single-tenant) | **OIDC**; sessions |
| AuthZ | queries already merchant-scoped | **RBAC** (merchant / operator / ZarinPal-internal); tenant-scoped queries enforced at the boundary |
| Multi-tenancy | one dataset | tenant id on every row/query; isolation tests |
| Persistence/backups | rebuildable marts | backups of Postgres + object storage; mart rebuild jobs |
| AI | direct OpenRouter call | centralized **model gateway** (already abstracted) + centralized AI telemetry |

### CPU/RAM guidance (measured-only)
- Local dev / demo: ~1 vCPU, 2–4 GB RAM is comfortable (DuckDB is memory-bound on mart size).
- Production numbers require load testing against the real warehouse — **do not size from the
  hackathon dataset.**

### Security boundaries at the edge
- `/api/admin/*` is operator-scoped by design; in production put it behind RBAC (operator role).
- The LLM boundary (`ai/safe_context.py`) already strips everything sensitive; keep it on the path.
- Never send env vars or SQL to a model; never expose unbounded SQL tools.
