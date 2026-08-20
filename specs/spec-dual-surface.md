# Spec — Zarbin Dual-Surface Platform (Phase 3)

## Problem
Zarbin today is a single merchant dashboard. The vision is **two product surfaces
over one trusted analytical intelligence platform**:
1. **Merchant Workspace** — the individual merchant's insight-first dashboard (exists; improve).
2. **Control Center** — operations surface for business/product/data/AI/eng teams:
   platform health, product performance, AI operations & cost, data-source status.

Both must share the same deterministic semantic/data/insight layer. AI may *explain*
but must never be the source of any number, metric, or causal claim.

## Architecture decision (summary; full ADR in docs/ADR/0001)
**KEEP** Python + FastAPI + DuckDB + Parquet + React + Vite + TS. It is the correct
choice for this stage: analytical correctness (columnar OLAP in-process), zero-infra
local reproducibility (judges run one command), fast dev, and clean module boundaries
that already isolate the pieces a production migration would swap (db.py → warehouse,
marts → object storage). Adding Postgres/ClickHouse/Redis/queues now buys nothing the
dataset size needs and costs local reproducibility. Migration path documented, not built.

## Scope (this phase)
### Backend (`zarin/`)
- `ai/` — provider abstraction (`AIProvider`), `OpenRouterProvider` (stdlib urllib, no new dep),
  **free-model allowlist policy** (default free; reject/normalize non-free to `openrouter/auto` free
  routing), evidence-safe context builder, AI telemetry store (JSONL append + in-memory agg),
  AI response contract, grounding guard (LLM may not introduce numbers absent from evidence).
- Copilot v2: question → intent plan → deterministic tools (existing analytics) → structured
  evidence → optional LLM explanation → grounded answer. Numbers always deterministic. No key /
  provider error / grounding-fail ⇒ deterministic answer verbatim (never blocks).
- `sources/` — `DataSourceAdapter` protocol; `zarinpal` (real, marts); `ga4` (config-gated on
  `GA4_PROPERTY_ID`, honest "not_configured"/"error" status, no vendor SDK coupling); cross-source
  insight logic (traffic→payment) that fires only when both sources present & definitions compatible.
- Request-telemetry middleware → per-endpoint latency P50/P95/P99, error rate, throughput.
- Control Center API `/api/admin/*`: platform, performance, ai-ops, sources, platform-insights, ai-eval.
- AI eval framework (`ai/eval/`): representative Persian cases + expectations; offline runner
  (deterministic correctness + grounding + refusal); `python -m zarin.ai.eval`; report endpoint.

### Frontend (`frontend/src/`)
- Two workspaces with a prominent switch. Merchant surface unchanged in spirit (calm, insight-first).
- Control Center pages (denser, operational, still premium): Overview, Product Performance, AI Ops, Data Sources, Ops Copilot.
- Copilot upgrade (both surfaces): richer chat, **voice-to-text** (Web Speech API + graceful fallback),
  grounded/AI badge, 👍/👎 feedback, evidence drawer.
- Accessible **tooltip** component (progressive disclosure; hover + keyboard focus + tap) for any
  technical term (P95 etc.). Simple Persian label on the surface; explanation in the tooltip.

### Docs
memory.md; docs/ADR/*; docs/DEPLOYMENT_SPEC.md; docs/PLATFORM_BOOK.md; CONTRIBUTING.md;
docs/DESIGN.md update; README rebuild; ARCHITECTURE/ANALYTICS update.

## Acceptance criteria
1. `uv run zarin` builds marts if missing and serves both surfaces at one URL; switch is one click.
2. Copilot returns correct deterministic numbers **with zero keys and zero network** (offline).
3. With `OPENROUTER_API_KEY` set, only free models are ever requested; a configured non-free model is
   rejected or normalized to free — proven by test.
4. External model never receives raw payment rows, card keys, session ids, SQL params w/ identifiers,
   or secrets — proven by test on the safe-context builder.
5. AI never changes a deterministic metric value — proven by test (numbers in answer ⊆ evidence).
6. AI telemetry + request telemetry recorded and surfaced in Control Center; zero fabricated metrics.
7. GA4 unconfigured ⇒ honest status, product still fully works; adapter add path documented.
8. AI eval runner produces per-dimension indicators (deterministic / grounding / refusal), not one score.
9. New + existing tests pass; ruff clean; frontend `tsc --noEmit && vite build` clean.
10. Merchant & Control Center visually distinct, RTL-correct, accessible, no template/gradient-AI look.

## Security boundaries
- Secrets only from env (`OPENROUTER_API_KEY`, `GA4_PROPERTY_ID`, `GOOGLE_APPLICATION_CREDENTIALS`); never committed, never sent to a model.
- LLM gets only computed metrics/aggregates/methodology/confidence/caveats — never raw SQL, env, or row data.
- LLM cannot construct SQL; only bounded deterministic analytical tools are exposed.
- Prompt-injection: system prompt fixed; user text is data; output grounding-checked; on any doubt → deterministic fallback.
- `/api/admin/*` documented as operator-scoped; hackathon build is single-tenant (auth path documented, not enforced).

## Non-goals (this phase; documented as future)
Live GA4 pull without creds; live paid-LLM calls; production auth/RBAC/multi-tenant enforcement;
warehouse/queue/Redis infra; persistent DB for telemetry (JSONL is the hackathon store).
