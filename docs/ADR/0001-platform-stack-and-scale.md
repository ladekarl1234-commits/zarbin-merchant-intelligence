# ADR-0001 — Platform stack, dual-surface architecture, and scale path

**Status:** Accepted for challenge / production-shaped architecture  
**Decision date:** 2026-08-20

## Context

Zarbin started as a challenge product over ~2.2M payment attempts. The product now has two distinct audiences:

1. merchant-facing analytics and actions;
2. business/technical control plane for data, AI quality, performance, turnaround and cost.

It must remain easy to run locally while allowing future ingestion from APIs such as Google Analytics and AI-assisted analysis without turning the LLM into the source of truth.

## Decision

Keep the current core stack, but make its boundaries explicit:

- **React + Vite + TypeScript** for the browser UI;
- **FastAPI** for domain APIs and the control plane;
- **DuckDB + Parquet** for current analytical marts;
- deterministic semantic/metric engine as the authoritative source of numbers;
- external data behind connector adapters;
- external AI behind an AI Gateway (`zarin/ai_ops.py`), defaulting to `openrouter/free` when configured;
- separate Merchant and Control Center surfaces over the same domain API.

## Why this stack is the best fit now

### FastAPI vs Node-only backend

FastAPI keeps analytical Python code, DuckDB and data-science logic in one process and avoids duplicating metric logic in JavaScript. It also gives typed OpenAPI and is easy to split into services later.

### React/Vite vs Next.js

The current application is an authenticated-style analytical SPA, not a content/SEO site. SSR is not required for the core product. Vite gives a smaller operational surface and the built frontend can be committed for judge-friendly Node-free execution. If the public product later needs server-rendered marketing, auth middleware or edge rendering, a separate Next.js shell can be added without changing the analytical API.

### DuckDB/Parquet vs Postgres-only analytics

For a few million analytical rows and complex local scans, DuckDB is fast, reproducible and radically simpler than operating a warehouse. Postgres is a better future control-plane store, not necessarily the best current OLAP engine.

### Why not Spark/Kafka/Kubernetes now

They solve scale and streaming problems the challenge does not have and would reduce reproducibility and judge experience. The architecture leaves insertion points for queues/workers later.

## Scalability truth

The current deployment is **single-node production-shaped**, not horizontally scalable multi-tenant infrastructure.

What scales today:

- features can be added through modules/adapters;
- UI surfaces can grow independently;
- FastAPI routes can be separated later;
- external sources do not modify core metric definitions;
- the AI provider can be swapped;
- DuckDB comfortably handles the challenge volume.

What does not scale horizontally yet:

- local Parquet/marts as mutable shared state;
- JSONL AI telemetry;
- evaluator-mode identity;
- synchronous external source refresh;
- one-process cache/state assumptions.

## Production scale migration

When concurrency/tenant count requires it:

- raw files -> object storage;
- control-plane state -> Postgres;
- high-concurrency analytics -> ClickHouse/warehouse;
- sync jobs -> queue + workers;
- telemetry -> OpenTelemetry + durable metrics/log store;
- secrets -> secret manager;
- auth -> OIDC/RBAC + tenant-scoped policies.

These are substitutions behind existing boundaries, not a rewrite of merchant metric semantics.

## AI architecture

The LLM is intentionally not allowed to calculate business numbers. Flow:

`question -> deterministic analytics -> evidence-safe context -> optional OpenRouter explanation -> response + telemetry`

If OpenRouter fails, the deterministic answer remains available. `openrouter/free` is the default configured route so model selection can remain free-model-only while preserving provider abstraction.

## Consequences

### Positive

- simplest stack that fits current data;
- reproducible locally;
- low operational cost;
- clear path to GA4 and additional sources;
- AI can improve language/analysis without compromising metric correctness;
- two audiences can evolve independently.

### Negative / accepted debt

- no horizontal analytics scale yet;
- browser-native voice is not the final enterprise STT solution;
- AI telemetry is local until observability infrastructure exists;
- GA4 sync requires optional SDK/credentials.

## Rejected alternatives

- **Full Next.js rewrite:** little immediate value, high regression risk.
- **Postgres for all analytics:** worse local OLAP ergonomics for this dataset.
- **LLM-first analytics:** unacceptable hallucination/traceability risk.
- **Microservices now:** complexity without score/business value.
