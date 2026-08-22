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
  zarin/pipeline.py (build) │   ZSTD-15, sorted by merchant_key,d,<unique key>
  zarin/db.py (access)      ├─► analytics.py / insights.py / peers.py  (deterministic metrics)
  zarin/registry.py         │        │
   (metric SoT + evidence)  │        ├─► nlu.py (intent retrieval) ─► copilot.py (merchant)
                            │        │                                  └─► ai/gateway.py
                            │        └─► ops_copilot.py (ops)         ─► ai/gateway.py
  zarin/control.py ─ platform/performance/ai-ops/sources                       │
  zarin/cache.py  ─ response cache + CDN Cache-Control                          ▼
  zarin/obs.py ─ request telemetry     zarin/ai/telemetry.py ─ AI telemetry  [optional] OpenRouter
  zarin/sources/ ─ DataSourceAdapter (zarinpal=truth, ga4=gated)
  zarin/api.py (FastAPI) ─► /api/* + /api/admin/* + static SPA (React/Vite/TS)
```

## Copilot routing — READ BEFORE TOUCHING copilot.py
Three stages, precision first. Full rationale + measurements: `docs/RETRIEVAL.md`.
1. **Safety families** (`_OUT_OF_SCOPE`): forecast · external_market · pii · injection ·
   not_in_dataset · greeting. Run FIRST, against raw AND normalised text. Each one closed a
   measured failure — without them the router answered 15 of 40 questions it should refuse.
2. **Exact rules** (`_RULES`, ORDERED): rule-by-rule against raw AND normalised, never
   all-rules-against-raw-first — spelling must not beat rule priority. The order encodes real
   opinions: psp("which gateway") > peers("rank among") > changes > hours > recovery >
   amount_bands > friction > … Do not reorder without re-running the retrieval eval.
3. **Retrieval** (`nlu.py`): TF-IDF centroid over 13 intent documents (examples + anchors×4).
   score ≥ ACCEPT → route · ≥ REJECT → clarify · below → unrecognised (offers alternatives).
- **`out_of_scope` is NOT a retrievable class.** "Everything else" cannot be enumerated.
- **Every constant in nlu.py is set by `pipeline/calibrate_nlu.py` (leave-one-out over the
  bank ONLY).** Never tune them against `zarin/ai/eval/retrieval*_cases.py` — those measure
  generalisation, and tuning on them destroys the only honest number in the project.
- `route_detail()` is the single routing implementation. `_plan` and the evaluation both call
  it; there is no second copy to drift.

## Deployment invariants (Vercel) — `docs/DEPLOY_VERCEL.md`
- `.vercelignore` MUST exist. Without it Vercel falls back to `.gitignore`, which excludes
  `data/` — and the function ships with no marts.
- `ZARIN_SESSION_SECRET` MUST be set: otherwise auth.py generates a per-process secret and
  tokens break at random when a second instance warms up.
- `ZARIN_TELEMETRY_DIR=/tmp/...` — everything else is read-only.
- `ZARIN_HOST` non-loopback ⇒ `/api/admin/*` requires a signed ops-scope session.
- The LLM is NEVER on the answer path. `/api/copilot` is deterministic; `/api/copilot/polish`
  is the opt-in rephrasing pass the client calls after rendering. Measured: the best free
  model adds 3.2s and is rejected by the grounding guard ~1 time in 5.
- `zarin/cache.py` CACHEABLE must never include `/api/copilot` (telemetry side effect) or
  `/api/admin/*` (the guard runs after middleware).
- `db.reset()` calls `invalidate_derived()`. Any new `lru_cache` over the marts must be added
  there, or swapping MARTS_DIR silently serves the previous dataset.

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
- **Polarity is checked in BOTH directions.** A model that DROPS a negation inverts the claim
  exactly as one that adds it: observed live, «مبلغ پرداخت تاییدنشده» came back as
  «تاییدشده» with every digit intact. `_POLARITY_MARKERS` flags a marker the engine used and
  the model did not, and a marker the engine never used at all — but NOT a marker already
  present being repeated, because rejecting faithful rephrasings is how the LLM path silently
  degrades to a no-op.
- With **no `OPENROUTER_API_KEY` the product runs fully offline** on the deterministic engine.
- **Free-model policy** (`ai/models.py`): allowed iff model id ends `:free` (or in an explicit
  allowlist). `openrouter/auto` is REJECTED (it bills). A configured non-free model is forced to
  the default free model. Default is free.
- **Evidence-safe context** (`ai/safe_context.py`): the model receives only computed
  metrics/definitions/methodology/caveats. NEVER raw rows, card ids, session ids, executed SQL,
  query params, or secrets. `assert_safe()` fails loudly on any leak.
- The LLM cannot construct SQL; only bounded deterministic tools produce numbers.

## Important env vars
`OPENROUTER_API_KEY` (optional; enables `/api/copilot/polish`) · `OPENROUTER_MODEL` (default
lives in `ai/models.py` next to the measurement that chose it; `deepseek/...:free` is DEAD on
OpenRouter — do not restore it) · `GA4_PROPERTY_ID` +
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
Commit `75de6bb` was audited by a 15-lens expert panel; 43 of the 44 critical/high findings were
independently verified (ZB-044 was missed by the per-lens cap). **Before starting new work, read
`docs/EXPERT_REVIEW.md` §6 (priority queue) and pick from `docs/EXPERT_REVIEW_ISSUES.md`** — issues
have stable IDs (`ZB-001`…`ZB-120`). Fix **ZB-120 first**: `ntile(5) OVER (ORDER
BY amount)` in `insights.py:209` has no tiebreaker, so `high_value_friction` returns a *different*
impact figure on identical calls — it breaks the determinism claim on the surface built to prove it.
Other high-value themes:
the realized-GMV cap lives only in `_gap_card`, leaving three generators uncapped (ZB-006); the evidence drawer's
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
