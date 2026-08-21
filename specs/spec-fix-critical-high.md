# Spec — Fix all critical & high findings (ZB-001…ZB-044, ZB-120)

45 issues: 5 critical, 39 high (panel) + ZB-120 (record verification).
Source of truth: `docs/EXPERT_REVIEW_ISSUES.md` / `docs/expert_review_findings.json`.

## Batches (file ownership is disjoint so batches can run in parallel)

**A — analytics core** (`zarin/insights.py`, `registry.py`, `peers.py`, `analytics.py`) — done by lead
ZB-120 determinism · ZB-006 cap all generators · ZB-015 score unit · ZB-024 query hoisting ·
ZB-016 PSP selection bias · ZB-018 window parity · ZB-007/011/014/017 registry↔code formula ·
ZB-012 decompose generate() · ZB-028 verify_type diagnosis · ZB-029 claimability age · ZB-003 empty-state signal

**B — AI layer** (`zarin/ai/*`, `copilot.py`, `ops_copilot.py`) — done by lead
ZB-004/020 non-numeric grounding · ZB-038 scale-word rule · ZB-039 unit binding · ZB-040 real refusal
intent · ZB-008 intent coverage · ZB-032 honest fallback · ZB-013 count-vs-rial formatting

**C — API / infra / security / perf** (`api.py`, `db.py`, `obs.py`, `config.py`, `control.py`, `pipeline.py`) — agent
ZB-001/030 session-bound merchant scope · ZB-019 admin fail-closed off-loopback · ZB-002 per-thread
cursors · ZB-023 mart clustering · ZB-025 anomaly caching · ZB-021 500s in telemetry · ZB-010
hardcoded anomaly count · ZB-009 typed API contract · ZB-026 merchant drilldown endpoint

**D — frontend** (`frontend/src/**`) — agent
ZB-035 contrast tokens · ZB-036 focus ring · ZB-037 zero-size buttons · ZB-033 tooltip RTL mirroring ·
ZB-034 cohort ramp · ZB-031 wire tooltips · ZB-022 meta failure banner · ZB-027 card CTA/state ·
ZB-026 merchant table UI · ZB-032 fallback UI · ZB-003 empty-state UI · auth token in `api.ts`

**E — tests** (`tests/**`, `frontend` vitest) — after A–D
ZB-005 peer happy path · ZB-041 LMDI attribution · ZB-042 generator coverage · ZB-043 frontend tests +
fa/fmt parity · ZB-044 ops routing table · regression test per fixed issue

## Cross-batch contracts (fixed up front so batches don't diverge)
- **Auth (C→D):** `POST /api/auth/session {scope:"merchant"|"ops", merchant_key?}` → `{token}` (HMAC,
  server secret). Merchant routes resolve `m` from the token when `ZARIN_REQUIRE_AUTH=1`; otherwise
  demo mode keeps the query param. `get()` in `api.ts` sends `Authorization: Bearer <token>`.
- **Drilldown (C→D):** `GET /api/admin/merchants?sort=unverified|no_attempt|gmv_delta&limit=` →
  `{rows:[{merchant_key, category_title, gmv, paid_unverified_amount, no_attempt_rate, ...}]}`.
- **Impact formatting (A→B):** one shared `format_impact(card)` helper; copilot must not re-implement it.

## Acceptance
1. Every one of the 45 issues is either fixed in code, or explicitly recorded as deliberately deferred
   with a reason (no silent skips).
2. `uv run pytest -q` green with new regression tests; `uv run ruff check .` clean;
   `cd frontend && npm run build` clean; `uv run python -m zarin.ai.eval` green.
3. Determinism: two consecutive `generate()` calls return identical impact figures (test).
4. No opportunity card exceeds realized GMV without `capped=True` (test over many merchants).
5. Product still runs offline with zero keys; both surfaces work desktop + mobile.
6. `docs/EXPERT_REVIEW*.md` gain a status column so the record stays auditable after the fixes.

## Non-goals
Re-running the 15-agent panel (that re-scores; separate task). Changing product scope beyond what a
finding requires.
