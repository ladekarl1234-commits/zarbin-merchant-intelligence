# ADR-0004 — External data sources via a DataSourceAdapter

Status: Accepted · Date: 2026-08

## Context
The challenge dataset must not be the only conceptual source forever. GA4 is the first future
source; CRM/accounting/ads/support/marketing follow. The semantic layer must not couple to any
vendor SDK, and new data must produce *insights*, not just more charts.

## Decision
- A **`DataSourceAdapter`** protocol (`zarin/sources/base.py`): `id`, `name_fa`, `status()` →
  `SourceStatus` (configured / connected / status / freshness / is_truth / note), and
  `metrics(f,t)` → safe aggregates or `None`.
- `ZarinPalAdapter` wraps the marts and is flagged **`is_truth`** (source of financial truth).
- `GA4Adapter` is **config-gated** on `GA4_PROPERTY_ID` + `GOOGLE_APPLICATION_CREDENTIALS`, with an
  **injectable transport** (`fetch_fn`) so the GA4 Data API call is testable and no Google SDK is
  coupled in. Unconfigured → honest `not_configured`; configured w/o transport → `error`; it never
  breaks the product.
- A **source registry** feeds Control Center → Data Sources.
- **Cross-source insights** (`sources/insights.py`) relate GA4 traffic to payment truth only as
  aggregate, time-aligned **relationships with an explicit no-causality caveat** — never a
  row-level join (no legitimate identity mapping) and never merging GA4 "revenue" with payment GMV.

## Insight framework for any new source
`Source → Normalize → Quality checks → Semantic metrics → deterministic analyses → candidate
insights → confidence/suppression → action ranking → evidence → [optional] AI explanation.`
`Source → LLM → random insight` is forbidden.

## Consequences
- Adding Shopify = one adapter file; the engine and UI generalize.
- "Payment truth" vs "web/product analytics signal" is a documented, enforced distinction.

## Rejected
- Coupling GA4's Python SDK into the semantic layer (untestable, heavy, credential-bound).
- Row-level GA4↔payment joins or causal claims across sources.
