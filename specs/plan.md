# Plan — Zarbin

## Stack decision
- Python 3.13 + DuckDB: pipeline (CSV.gz → Parquet marts) + FastAPI API querying marts live.
- Frontend: Vite + React + TypeScript, RTL, Vazirmatn (bundled), hand-styled design system on
  ZarinPal brand tokens; recharts for charts (styled), custom funnel/percentile/waterfall SVG.
- Single process serve: FastAPI serves /api/* and the built frontend (committed dist → zarin/static).
- Rationale: 2.2M rows is DuckDB territory; live queries give genuine traceability (the SQL shown in
  the evidence drawer is the SQL that ran); uv gives judges a one-command run without Docker.
  Tradeoff: committed frontend build (~a few hundred KB) buys Node-free judge experience.

## Modules
1. zarin/config.py — paths, constants, thresholds.
2. zarin/pipeline.py — build marts + integrity assertions (session-constancy, grain uniqueness).
3. zarin/db.py — duckdb connection, query helper w/ dict rows.
4. zarin/registry.py — METRICS registry (single source of truth) + evidence builder.
5. zarin/analytics.py — overview, funnel, temporal, customers, decomposition (LMDI).
6. zarin/peers.py — peer group construction, percentiles, suppression.
7. zarin/insights.py — insight generators + ranking (impact × confidence, effort-tiered).
8. zarin/copilot.py — deterministic Persian intent router → analytics → answer w/ evidence refs.
9. zarin/api.py — FastAPI endpoints + static serving.
10. zarin/__main__.py — build-if-missing + uvicorn.
11. tests/ — fixtures (synthetic CSV covering danger cases) + metric/insight/peer/api tests.
12. frontend/ — src/{api,theme,components,pages}; pages: Overview(ActionFeed), Funnel, Customers,
    Peers, Changes, Copilot, DataQuality; global EvidenceDrawer; merchant/period switcher;
    bottom-nav mobile layout.

## Order
1. pipeline + marts (verify counts vs audit)
2. registry + analytics + peers + insights + copilot (pure Python, testable)
3. tests (fixtures first, danger list)
4. API
5. frontend (design system → pages → evidence drawer → mobile)
6. build + integrate + Playwright viewport checks
7. analytical QA (docs/VALIDATION.md: cross-check UI numbers vs independent SQL for 3 merchants)
8. docs
9. adversarial review panel (correctness/analytics lens, UX/frontend lens, data-integrity/security lens)
10. fixes, re-test, git, converge

## Risks
- Frontend scope creep → cap pages at 7, share components aggressively.
- OneDrive path (spaces) → always quote; avoid long node_modules paths issues.
- Peer sparsity in small categories → suppression thresholds + category fallback.
- March composition trap → like-for-like framing built into decomposition, not a footnote.
