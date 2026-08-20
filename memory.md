# memory.md — Zarbin engineering & product continuity

Persistent memory for the next engineer / AI agent. Not a README duplicate: this is
"what you must know before you change anything." Keep it concise and current.

## What Zarbin is
**Zarbin (زرین‌بین)** turns a ZarinPal payments dataset into decisions, on **two
surfaces over one deterministic intelligence platform**:
1. **Merchant Workspace** — insight-first dashboard for one merchant (What happened →
   Why it matters → What may explain it → Estimated impact → What to do → Confidence → Evidence).
2. **Control Center** — operations surface (business/product/data/AI/eng): platform
   health, product performance, AI operations & cost, data-source status. "How is Zarbin itself doing?"

## Architecture (one shared semantic layer)
```
DuckDB over Parquet marts  ─┐
  zarin/pipeline.py (build) │
  zarin/db.py (access)      ├─► analytics.py / insights.py / peers.py  (deterministic metrics)
  zarin/registry.py         │        │
   (metric SoT + evidence)  │        ├─► copilot.py (merchant)  ─► ai/gateway.py ─► [optional] OpenRouter
                            │        └─► ops_copilot.py (ops)   ─► ai/gateway.py
  zarin/control.py ─ platform/performance/ai-ops/sources
  zarin/obs.py ─ request telemetry     zarin/ai/telemetry.py ─ AI telemetry
  zarin/sources/ ─ DataSourceAdapter (zarinpal=truth, ga4=gated)
  zarin/api.py (FastAPI) ─► /api/* + /api/admin/* + static SPA (React/Vite/TS)
```

## Analytical invariants — NEVER break these
- **Grain: 1 dataset row = 1 payment attempt. All metrics are session-grain.**
  `session_key` (+`try_seq`) is unique. Retries must never inflate counts/GMV.
- **Success = session_status Verified.** `Paid` = money settled at bank but merchant
  never verified → reported separately as **paid_unverified** (real settled money, not an estimate).
- **Five behavioral outcomes are distinct:** verified / paid_unverified / no_attempt /
  abandoned_inbank / failed_bank (+reversed). **NoAttempt (try_seq=0) ≠ bank failure** —
  the payer never reached a PSP.
- **`recovered` = Verified AND n_tries>1 AND first try not ok.** Paid-after-retry is NOT recovered.
- **Opportunity = counterfactual** (gap × sessions × own conv × own ticket), capped at
  realized GMV. **NEVER "lost revenue = Σ failed amounts."**
- **`adjusted_fee` is NOT the real fee** — a privacy multiplier is applied. Use only as a
  **relative index** ("شاخص نسبی کارمزد"). Never present as toman/rial fee.
- **Customer scope:** `payer_card_key` exists only on completed attempts and is not shared
  across merchants → customer analysis covers only *this merchant's successful payers*.
- Currency is **IRR (rial)** everywhere.

## AI grounding rules — NON-NEGOTIABLE
- The **deterministic engine is the source of truth for every number.** The LLM may only
  rephrase. `ai/gateway.py` runs a **grounding guard**: any answer introducing a number the
  engine didn't compute is discarded and the deterministic text is returned (fallback).
- With **no `OPENROUTER_API_KEY` the product runs fully offline** on the deterministic engine.
- **Free-model policy** (`ai/models.py`): allowed iff model id ends `:free` (or in an explicit
  allowlist). `openrouter/auto` is REJECTED (it bills). A configured non-free model is forced to
  the default free model. Default is free.
- **Evidence-safe context** (`ai/safe_context.py`): the model receives only computed
  metrics/definitions/methodology/caveats. NEVER raw rows, card ids, session ids, executed SQL,
  query params, or secrets. `assert_safe()` fails loudly on any leak.
- The LLM cannot construct SQL; only bounded deterministic tools produce numbers.

## Important env vars
`OPENROUTER_API_KEY` (optional; enables LLM rephrasing) · `OPENROUTER_MODEL` (default
`deepseek/deepseek-chat-v3-0324:free`, policy-enforced) · `GA4_PROPERTY_ID` +
`GOOGLE_APPLICATION_CREDENTIALS` (optional GA4) · `ZARIN_ADMIN_TOKEN` (set → `/api/admin/*` needs `X-Admin-Token`) · `ZARIN_PORT` (8630) · `ZARIN_HOST` ·
`ZARIN_DATA_PATH` · `ZARIN_MARTS_DIR` · `ZARIN_TELEMETRY_DIR`.

## Deployment
Local: `uv run zarin` (builds marts if missing, serves both surfaces at
`http://localhost:8630`; Control Center = "مرکز کنترل" switch top-right, or `#/ops/overview`).
Rebuild frontend: `cd frontend && npm run build` (outputs to `zarin/static`). Prod-shaped
migration path in `docs/DEPLOYMENT_SPEC.md`.

## External data
GA4 is the first future source, via `zarin/sources/ga4.py` (config-gated, injectable
transport, no vendor SDK coupling). **GA4 = web/product signals, NOT financial truth**;
never row-level joined with payments — only aggregate, time-aligned relationships, no causality.

## Known issue queue (from the expert audit)
Commit `75de6bb` was audited by a 15-lens expert panel; every critical/high finding was independently
verified. **Before starting new work, read `docs/EXPERT_REVIEW.md` §6 (priority queue) and pick from
`docs/EXPERT_REVIEW_ISSUES.md`** — issues have stable IDs (`ZB-001`…`ZB-119`). Highest-value themes:
the realized-GMV cap covers only one of four opportunity generators (ZB-006); the evidence drawer's
opportunity formula contradicts the code (ZB-007/014/017); the grounding guard is digit-only so
invented causality passes (ZB-004/020/038/039); the AI eval's "refusal safety" cannot fail (ZB-040);
peer-percentile happy path and 6/9 card generators are untested (ZB-005/042); accessibility contrast
fails WCAG 1.4.3 (ZB-035). Fixing the claim-vs-enforcement gap outranks adding features.

## Current limitations (be honest)
- Opportunity band is a scenario range, not a bootstrap CI (labelled as such; low-peer-n flagged).
- Telemetry store is JSONL + in-memory (hackathon). Prod → durable store/OTel (see ADR-0001).
- Single-tenant; no auth/RBAC enforced (design in DEPLOYMENT_SPEC; queries are already merchant-scoped).
- GA4 live pull and paid-LLM calls are config-gated (no creds in the challenge env).
- Copilot NLU is intent-regex + optional LLM rephrase; paraphrase coverage is bounded.

## Bugs already fixed (don't reintroduce)
- Repeat-rate must be **in-period** (`count(*) OVER (PARTITION BY card)`), not lifetime.
- Path traversal: SPA route decides containment **lexically** (`os.path.normpath`), never
  `Path.resolve()` (UNC → SMB/NTLM leak on Windows).
- PSP "friction" card guarded against degenerate rails (`ok_rate≥0.05 and successes≥30`).
- `/api/changes` reassigns *normalized* dates (basic-ISO would 500 otherwise).
- DuckDB reserved-ish aliases (`rows/months/nulls`) → `n_rows/...`.

## Decisions rejected (and why)
- **Rewrite to Next.js/Postgres/ClickHouse now** — no: dataset fits DuckDB in-process; local
  reproducibility (one command, no infra) is worth more than premature scale. See ADR-0001.
- **LLM-first analytics** — forbidden: `Source → LLM → insight` is banned; numbers must be
  deterministic and traceable. See ADR-0002.
- **`openrouter/auto` as the free router** — no: it bills. Only `:free` ids. See ADR-0003.
