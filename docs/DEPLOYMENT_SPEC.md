# Deployment Specification

## Runtime profiles

### Local / judge mode

Goal: one-command, offline-first evaluation.

```bash
uv run zarin
# http://localhost:8630
```

- bind: `127.0.0.1:8630`
- challenge data: `data/other_challenge_data.csv.gz` or `ZARIN_DATA_PATH`
- marts: local Parquet
- external AI: optional; deterministic fallback always available
- GA4: optional and disabled by default

### Connected demo mode

Adds OpenRouter and optional GA4:

```bash
export OPENROUTER_API_KEY=...
export OPENROUTER_MODEL=openrouter/free
export GA4_PROPERTY_ID=123456789
export GOOGLE_APPLICATION_CREDENTIALS=/secure/path/service-account.json
uv sync --group connectors
uv run zarin
```

Never commit these secrets or credentials.

### Production target

The current codebase is single-node production-shaped. Recommended production topology:

- reverse proxy / TLS termination;
- FastAPI app replicas;
- Postgres for identity/control-plane state;
- object storage for raw and derived data;
- ClickHouse or managed analytical warehouse when concurrency outgrows DuckDB;
- queue + workers for ingestion/insight refresh;
- OpenTelemetry collector + metrics/log backend;
- secret manager;
- OIDC/RBAC;
- scheduled GA4 connector jobs;
- model policy gateway and evaluation dataset.

## Environment contract

| Variable | Required | Meaning |
|---|---:|---|
| `ZARIN_DATA_PATH` | local default exists | payment dataset path |
| `ZARIN_MARTS_DIR` | no | derived analytical marts |
| `ZARIN_HOST` | no | bind host; default localhost |
| `ZARIN_PORT` | no | default 8630 |
| `OPENROUTER_API_KEY` | no | enables external AI explanation |
| `OPENROUTER_MODEL` | no | default `openrouter/free` |
| `ZARIN_AI_EVENTS_PATH` | no | local AI telemetry path |
| `GA4_PROPERTY_ID` | no | GA4 property |
| `GOOGLE_APPLICATION_CREDENTIALS` | no | service-account credential path |
| `ZARIN_EXTERNAL_DIR` | no | external-source snapshots |

## Service boundaries

- `/api/*`: merchant analytics
- `/api/copilot`: deterministic analytics + optional AI explanation
- `/api/admin/ops`: control center telemetry
- `/api/admin/ga4/sync`: optional source sync
- static SPA: merchant and control-center surfaces

## SLO starting targets

These are engineering targets, not claims about current SLA:

- API P95 < 1s for warm analytical queries;
- AI grounded-answer rate >= 98%;
- AI fallback rate < 5% when provider configured;
- request success >= 99%;
- zero raw payment-row leakage to external model providers.

## Security posture

Before internet exposure:

- add authentication and tenant authorization;
- protect state-changing admin routes with RBAC and CSRF strategy where relevant;
- keep raw evidence tenant-scoped;
- store secrets outside filesystem/repository;
- add rate limiting and abuse controls;
- define retention for AI telemetry;
- audit model/provider data processing terms;
- disable public GA4 sync unless authorized.

Current default bind to localhost is intentional until those controls exist.

## Data-source ingestion contract

Every new connector should implement the same conceptual stages:

1. authenticate;
2. fetch bounded data;
3. validate schema/freshness;
4. persist a source snapshot or normalized landing table;
5. map source dimensions to semantic metrics;
6. run data-quality gates;
7. only then expose source-derived insight.

No connector may bypass metric definitions or let an LLM infer a business number directly from arbitrary raw payloads.

## Rollback

The challenge path remains isolated and deterministic. If an external connector or model fails:

- merchant analytics continue from existing marts;
- copilot falls back to deterministic answers;
- Control Center surfaces the failure rather than hiding it.
