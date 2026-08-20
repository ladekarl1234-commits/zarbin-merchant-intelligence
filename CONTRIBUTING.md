# Contributing to Zarbin

## Repository map
```
zarin/                     Python backend (one shared semantic layer)
  config.py                central config / thresholds / env
  pipeline.py              build Parquet marts from the dataset (integrity asserts)
  db.py                    DuckDB access (views over marts, schema guard)
  registry.py              metric registry = single source of truth + evidence()
  analytics.py             session-grain metrics (overview, funnel, customers, changes)
  insights.py              opportunity engine / ranked action cards
  peers.py                 explainable peer benchmarking
  copilot.py               merchant copilot: deterministic plan → gateway
  ops_copilot.py           Control Center copilot: telemetry plan → gateway
  control.py               platform / performance / ai-ops / sources aggregations
  obs.py                   request telemetry (p50/p95/p99, error rate, throughput)
  store.py                 append-only event log (JSONL + in-memory ring)
  fa.py                    Persian number/text formatting (server sentences)
  api.py                   FastAPI: /api/* + /api/admin/* + static SPA
  ai/                      provider, models(free policy), safe_context, telemetry,
                           contract, gateway, eval/ (copilot evaluation)
  sources/                 DataSourceAdapter: base, zarinpal(truth), ga4(gated), insights
frontend/src/              React + Vite + TS (strict), RTL, Vazirmatn
  ctx.tsx                  app state + useData/useAdmin hooks
  App.tsx                  dual-surface shell + workspace switch + routing
  pages/                   merchant pages     ops/  Control Center pages
  components/              ui, Copilot(voice+feedback), Tooltip, EvidenceDrawer, charts
  theme.css                design system (merchant warm / ops cool)
docs/                      ANALYTICS, ARCHITECTURE, DATA_AUDIT, DESIGN, PLATFORM_BOOK,
                           DEPLOYMENT_SPEC, ADR/, JURY_REVIEW, VALIDATION, screenshots/
tests/                     pytest (metrics, insights/peers, api, ai, control, sources)
```

## Development setup
```bash
uv sync                      # Python env from the lock
cd frontend && npm ci        # frontend deps
uv run zarin                 # build marts if missing + serve on :8630
```
Windows/OneDrive: `UV_LINK_MODE=copy`.

## How to add …
**a metric** → add a `Metric(...)` to `zarin/registry.py`; compute it in `analytics.py` (stay
session-grain); build its evidence with `evidence(id, sql=…, params=…)`; surface via an endpoint;
add a test in `tests/test_metrics.py`.

**an insight (action card)** → add a `_…_card()` in `zarin/insights.py` returning the
Observation→Diagnosis→Impact→Action→Confidence→Evidence shape; rank by impact×confidence÷effort;
suppress on thin evidence; test in `tests/test_insights_peers.py`.

**an external source** → add `zarin/sources/<name>.py` implementing `DataSourceAdapter`
(`status()` + `metrics()`); register it in `sources/base.registry()`; if it relates to payments,
add aggregate, no-causality logic in `sources/insights.py`; test in `tests/test_sources.py`.

**an AI provider** → add a class implementing the `AIProvider` protocol in `zarin/ai/provider.py`;
wire it in `default_provider()`. Do not touch the analytics engine.

**a dashboard page** → merchant: `frontend/src/pages/`; ops: `frontend/src/ops/`. Add a route in
`App.tsx` (`MERCHANT` or `OPS`). Fetch with `useData` (merchant) or `useAdmin` (ops). Use `Term`
for any technical term (simple Persian label + tooltip).

**an evaluation case** → add a `Case(...)` to `zarin/ai/eval/cases.py` (expected intent, min
evidence, forbidden substrings, optional refusal). Run `uv run python -m zarin.ai.eval`.

## Required checks before a PR
```bash
uv run pytest -q            # all tests green
uv run ruff check .         # lint clean
cd frontend && npm run build   # tsc --noEmit (strict) + vite build clean
uv run python -m zarin.ai.eval # copilot eval indicators
```
CI (`.github/workflows/ci.yml`) runs the Python job (uv sync, ruff, pytest) and the frontend job
(npm ci, npm run build).

## Non-negotiables
Read `memory.md` first. Never break the analytical invariants (session grain; Verified=success;
paid_unverified is real settled money; adjusted_fee is a relative index only; opportunity is a
counterfactual, never Σ failed amounts). Never let the LLM produce a number. Never send raw
data/SQL/secrets to a model. Never weaken a test to get a pass.
