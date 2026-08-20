# ADR-0001 — Architecture & stack: keep DuckDB/FastAPI/React

Status: Accepted · Date: 2026-08 · Supersedes: none

## Context
Zarbin grew from a single merchant dashboard into a two-surface platform (Merchant +
Control Center) with a grounded AI copilot, telemetry, and pluggable external sources. The
current stack is Python + FastAPI + DuckDB + Parquet + React + Vite + TypeScript. The brief
asked us to *not automatically* keep it — to evaluate honestly against Next.js, Postgres,
ClickHouse, Timescale, Redis, queues, object storage, OpenTelemetry, and serverless.

## Problem
Pick the architecture that best balances analytical correctness, maintainability,
extensibility, scalability, dev speed, **local reproducibility**, performance, deployment
simplicity, judge experience, and future product development — without premature complexity.

## Options considered
1. **Keep DuckDB/FastAPI/React (chosen).**
2. Next.js full-stack + Postgres + Prisma.
3. Introduce ClickHouse/Timescale now for OLAP.
4. Add Redis + a queue/worker + object storage now.

## Decision — keep it
- **Analytical correctness:** DuckDB is a columnar OLAP engine *in-process*. Session-grain SQL
  over Parquet marts is exact and fast; the metric registry is the single source of truth.
  Measured: full pipeline build ~33s; warm API < 0.7s on a 1.05M-session merchant.
- **Local reproducibility (decisive for a hackathon):** `uv run zarin` builds marts if missing
  and serves everything at one URL. **Zero external services**, zero network, zero keys. A judge
  runs one command. Postgres/ClickHouse/Redis/queues would each add a service to stand up.
- **Clean seams already isolate what production would swap:** `db.py` (engine), `MARTS_DIR`
  (storage), `sources/` (ingestion), `obs.py`/`ai/telemetry.py` (telemetry), `ai/provider.py`
  (model gateway). Each is a file, not a cross-cutting rewrite.
- **Dev speed & DX:** FastAPI typed endpoints; React/Vite/TS strict; one metric registry; small,
  named modules.

## Why not the alternatives
- **Next.js:** would merge API+UI but buys nothing for a Python analytics engine; we'd either
  port analytics to TS (lose correctness/velocity) or run two runtimes. RSC/SSR is irrelevant to
  an authenticated internal analytics tool.
- **ClickHouse/Timescale now:** justified at 10^8–10^9 rows or multi-tenant concurrency, not at
  the current dataset. DuckDB covers today; the migration path below is real.
- **Redis/queue/object-storage now:** no measured need. Caching is `lru_cache` + in-memory rings;
  ingestion is a single deterministic build. Adding them now is complexity for appearance.

## Tradeoffs / consequences
- Single-process, in-memory telemetry: fine for one node; not durable/multi-node.
- DuckDB marts are local files: not concurrent multi-writer; rebuilt, not streamed.
- We accept these for the hackathon and document the migration path.

## Migration path (hackathon → multi-tenant production) — recommend only when justified
- Raw data → **object storage** (S3/GCS); marts materialized by a scheduled job.
- Control-plane state (tenants, users, feedback, telemetry) → **PostgreSQL**.
- Analytical warehouse → **ClickHouse** (or managed OLAP) when row counts / concurrency demand it;
  `db.py` is the only query seam to reimplement.
- Ingestion → **queue + workers** behind the `DataSourceAdapter` interface.
- **Redis** only if a measured cache-hit need appears.
- Observability → **OpenTelemetry** traces/metrics/logs replacing `obs.py`/`ai/telemetry.py` JSONL.
- **Secret manager**, **OIDC**, **RBAC**, **tenant-scoped queries** (already merchant-scoped),
  **audit logs**, background refresh, centralized **model gateway** (already abstracted).

## Quality-gate answers (what changes if…)
- *Add Shopify data?* → one file in `zarin/sources/` implementing `DataSourceAdapter`. Nothing in the engine.
- *OpenRouter disappears?* → implement one `AIProvider`; the deterministic product is unaffected (offline default).
- *Replace DuckDB with ClickHouse?* → rewrite `db.py` query execution; SQL is standard-ish; marts become CH tables.
- *Add auth?* → merchant queries are already parameter-scoped; add OIDC + a tenant filter at the API boundary.
- *100,000 merchants?* → first bottleneck is single-process marts/telemetry → object storage + warehouse + workers.
- *AI hallucinating?* → grounding guard + AI-Ops fallback/hallucination-risk metrics detect it now.
- *GA4 stops syncing?* → adapter `status()` flips to `error`; Control Center → Data Sources shows it.
- *One model slow?* → AI-Ops latency p95 per model surfaces it.
