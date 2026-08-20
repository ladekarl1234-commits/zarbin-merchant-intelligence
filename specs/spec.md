# Spec — Zarbin (زرین‌بین): ZarinPal Merchant Intelligence & Action Engine

## Problem
ZarinPal merchants get raw transaction history, not decisions. The hackathon asks for an
analytical product that turns the challenge dataset (2.21M payment attempts, 2.06M sessions,
343 merchants, 5 categories, Jan–Jun 2026) into **actionable, traceable, explainable** insights,
scored on: Actionability 90 / Correctness+Traceability 75 / Analytical depth 60 / Non-technical UX 45 / Technical quality 30.

## Product
**Zarbin (زرین‌بین)** — Persian-first, RTL, merchant-facing intelligence & action engine.
Not a wall of charts: an executive action feed backed by a deterministic metric registry,
peer benchmarking, decomposition, and an evidence drawer for every number.

## Verified data semantics (from audit, docs/DATA_AUDIT.md)
- Grain: one row = one payment attempt; `(session_key, try_seq)` unique; 0 duplicates.
- Session-level (constant within session): merchant, terminal, category, amount, adjusted_fee,
  session_status, created_at, expire_in (TTL = 30 min always), verify_type, verified_at, settled_at.
- Attempt-level: try_seq, try_status, psp_code, issuer_bank_code (success only), payer_card_key
  (terminal statuses only — structural missingness), switch_response_code (failures only),
  init_time_ms, verify_time_ms, try_created_at.
- `NoAttempt` ⇔ try_seq=0 ⇔ no PSP contact; never mixed with real tries in one session.
- session_status ∈ {Verified 1,025,655; Failed 1,028,477; Paid 8,706; Reversed 1}.
- `Paid` = settled at bank (`settled_at` set) but merchant never verified (`verified_at` null).
- Success = Verified session. GMV = Σ amount over Verified sessions (count once per session).
- Recovered session = Verified/Paid session whose first real attempt was not Verified/Paid (40,038).
- payer_card_key is merchant-scoped: 402,173 cards, zero cross-merchant overlap → no cross-merchant
  customer tracking; customer analytics cover successful payers only.
- adjusted_fee has a constant privacy multiplier → relative use only, labeled «شاخص نسبی کارمزد».
- Amounts are IRR (ریال).
- Known quirks documented, not silently repaired: ±sec clock jitter between created_at/try_created_at;
  28 Verified sessions without a Verified attempt row; 1 Reversed session; March merchant-composition drop.

## Functional requirements
FR1 Pipeline: one command builds Parquet marts from `data/other_challenge_data.csv.gz`
    (path overridable via ZARIN_DATA_PATH). Marts: sessions, attempts, merchant_daily,
    customers, merchant_stats.
FR2 Metric registry (semantic layer): single source of truth — id, Persian name, definition,
    formula, SQL, grain, caveats — used by API, insights, copilot, and evidence drawer.
FR3 Action feed: ranked opportunity/insight cards per merchant with
    Observation → Diagnosis → Quantified impact (interval) → Action → Confidence → Evidence.
    Insight types (data-verified): NoAttempt gap vs peers; in-bank abandonment gap; retry/recovery gap;
    paid-not-verified backlog; high-value friction; repeat-customer gap; GMV-change decomposition alert;
    customer concentration risk. Suppress on insufficient sample (thresholds in registry).
FR4 Funnel intelligence: Created → Attempted → Bank outcome → Paid → Verified; NoAttempt separated
    from bank failures; first-attempt vs eventual conversion; hour/amount-band views (within-merchant).
FR5 Customer intelligence: unique/new/returning, repeat share of txns+GMV, inter-purchase interval,
    monthly retention cohorts, concentration, dormant valuable customers. Successful payers only (labeled).
FR6 Peer benchmark: explainable peers = same category + similar scale band (see docs/ANALYTICS.md);
    percentiles with n shown; "why these peers" panel; suppression below minimum peer count.
FR7 What changed: LMDI (log-mean) decomposition of GMV change into sessions × conversion × ticket,
    per merchant, period vs comparison period; market vs like-for-like framing.
FR8 Evidence drawer on every prominent number: definition, formula, SQL, parameters, numerator,
    denominator, period, filters, sample size, caveats, sample session keys, computed-at.
FR9 Copilot: deterministic Persian Q&A answering from registry/analytics only (no LLM dependency;
    judges must be able to run offline).
FR10 Data-quality page: audit findings, exclusions, structural nulls, concentration, caveats.
FR11 Merchant switcher (evaluator mode) + date-range/comparison selection; curated demo merchants
     selected programmatically (e.g. M156, M43, M192/M265, M31) with reasons.
FR12 UI: Persian-first RTL, ZarinPal brand (yellow #FFD900 + near-black), Vazirmatn, responsive
     desktop + real mobile hierarchy, accessible (semantic HTML, keyboard, contrast, non-color cues).

## Non-functional
- One-command run for judges: `uv run zarin` (builds marts if missing, serves app+API on :8630).
  Dockerfile provided as convenience; uv path is the tested one.
- Interactive latency: API aggregates < ~300ms typical (DuckDB over Parquet; no browser recompute).
- Tests: pytest metric-correctness suite on deterministic fixtures covering the danger list
  (attempt-vs-session counting, retry inflation, NoAttempt vs bank failure, paid/verified semantics,
  merchant-scoped repeat, small-cohort suppression, fee labeling, opportunity ≠ sum of failures);
  frontend typecheck + production build; API smoke tests.
- No fabricated numbers anywhere; empty/insufficient states are explicit product states.

## Acceptance criteria
AC1 `uv run zarin` from a clean clone (with dataset in place) builds marts and serves the app; API
    endpoints return real data for any of the 343 merchants.
AC2 Every insight card and headline metric opens an evidence drawer w/ formula+SQL+n+caveats.
AC3 Funnel numbers for a hand-checked merchant match independent SQL (docs/VALIDATION.md).
AC4 Peer percentiles never render with < minimum peers; NoAttempt never counted as bank failure;
    GMV counts each session once (proven by tests).
AC5 adjusted_fee is surfaced only as a relative index with the caveat visible at point of use.
AC6 pytest, ruff, tsc, vite build all pass; results recorded in docs/VALIDATION.md.
AC7 Persian RTL UI works at 390px and 1440px widths; all critical features usable on mobile.
AC8 Docs exist: README, PRODUCT, DATA_AUDIT, ANALYTICS+METRICS, ARCHITECTURE, DESIGN, DECISIONS,
    VALIDATION, DEMO_SCRIPT; README maps features to the scoring rubric.
AC9 Repo committed with meaningful history; pushed to configured remote, or exact push blocker reported.

## Non-goals
- No real LLM integration (deterministic copilot instead — judges run offline).
- No cross-merchant customer identity claims; no geography; no causal claims (language:
  «برآورد», «مرتبط با», «فرصت قابل بازیابی»).
- No auth/multi-tenancy (evaluator mode assumes the merchant is selected).
