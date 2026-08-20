# The Zarbin Platform Book

*Why this product exists, and why it is built this way.* Written to be understood by a senior
engineer, a product manager, an investor, or a hackathon judge.

## 1. The merchant problem
A ZarinPal merchant has a payment gateway and a business — but not a data team. They don't want
analytics; they want answers: *Is my business getting better or worse? Why? What's unusual? Where
am I losing money? What should I do today?* Most tools hand them charts and leave the interpreting
to them. Zarbin does the interpreting.

## 2. Why payment data is uniquely valuable
Payment data is ground truth about money and intent. Every session tells you whether a customer
tried, reached the bank, paid, and was verified. It reveals not just revenue but **where revenue
leaks**: customers who never reached the gateway (NoAttempt), money that settled at the bank but
the merchant never verified (Paid-but-Unverified — *real, already-settled money*), and sessions
rescued by a retry. These are actionable in a way a page-view never is.

## 3. Why dashboards usually fail
They present metrics, not decisions. A wall of charts optimizes for "look how much we track,"
which raises cognitive load and buries the one number that matters. Zarbin inverts this: it leads
with a ranked **action feed**, and every claim carries its evidence one click away.

## 4. Zarbin is an Action Engine
Every major insight follows one shape: **What happened → Why it matters → What may explain it →
Estimated impact → What to do → Confidence → Evidence.** Opportunities are ranked by
impact × confidence ÷ effort. Impact is a **counterfactual** (a gap closed against a matched peer
baseline, valued at the merchant's own conversion and ticket, capped at realized GMV) — **never**
"lost revenue = sum of failed amounts," which would wildly overclaim.

## 5. Merchant workflow
Overview (executive summary + top opportunities) → Payment Funnel (the five distinct outcomes) →
What Changed? (exact decomposition of a GMV move) → Peers (why *these* comparable merchants) →
Customers (repeat, concentration, dormant-valuable) → Ask (the copilot). Every number has a
"محاسبه" button that opens an evidence drawer with the definition, method, the SQL that ran, its
parameters, sample size, caveats, and drill-through to source sessions.

## 6. The Control Center
A second surface for the people operating Zarbin — business, product, data, engineering, AI ops,
and potentially ZarinPal internal teams. It answers "How is Zarbin itself doing?": platform health
(merchants, sessions, GMV, concentration, platform-level opportunities and anomalies), product
performance, AI operations & cost, and data-source status — each framed as *is something wrong →
why → what to investigate*, not three vanity cards. It has its own copilot grounded in live
telemetry.

## 7. Deterministic analytics (the spine)
One semantic layer serves both surfaces. A **metric registry** is the single source of truth;
`analytics.py`/`insights.py`/`peers.py` compute at **session grain** (a retry never inflates a
count); `evidence()` builds the drawer payload from the real query. Correctness invariants
(Verified=success, NoAttempt≠failure, adjusted_fee is a *relative index* only, LMDI decomposition
sums exactly) are enforced in the pipeline and covered by tests.

## 8. Explainability
Traceability is a feature, not a footnote. The evidence drawer distinguishes «کوئری اجراشده»
(the exact SQL that ran) from «روش محاسبه» (method, when a figure is assembled from several
aggregates) — kept honest, never dressed up. Dates render in Jalali; every figure drills to
source rows.

## 9. AI architecture (grounded)
The copilot is deterministic-first: `question → intent plan → deterministic tools → structured
evidence → [optional] LLM rephrase → grounding guard → answer + AI response contract`. The LLM may
only make wording friendlier. A **grounding guard** rejects any answer that introduces a number
the engine didn't compute, falling back to the deterministic text. With no API key the copilot is
fully offline and identical in its numbers. See ADR-0002.

## 10. AI quality monitoring
We refuse to reduce AI quality to one score. AI-Ops separates **deterministic correctness**,
**grounding quality**, **language quality** (human-judged, not auto-scored), and **business
usefulness** (human-judged). Live telemetry tracks requests, fallback rate, grounded rate,
evidence coverage, zero-evidence answers, hallucination-risk events, latency p95, tokens, cost,
model/intent distribution, and 👍/👎 feedback. A small offline **eval harness**
(`zarin/ai/eval/`) runs representative Persian cases (sales decline, repeat customers, payment
failures/recovery, peers, opportunity, insufficient-data, misleading-causal, unavailable-metric,
malformed) and asserts intent, evidence, refusal, and no invented causality.

## 11. Source integrations & GA4
`DataSourceAdapter` (ADR-0004) makes the challenge dataset one input among many. GA4 is the first
future source — config-gated, no vendor SDK coupling, honest status when unconfigured. **GA4 is a
web/product signal, not financial truth.** It is never row-level joined with payments; only
aggregate, time-aligned relationships (traffic → payment sessions → payment success) with an
explicit no-causality caveat. New data must produce ranked, evidenced insights — never just
another chart.

## 12. Voice
Both copilots support **voice-to-text**: press the mic, speak Persian (`fa-IR` via the Web Speech
API), edit the transcript, send. If the browser lacks speech recognition the mic simply hides
(graceful fallback) — the product never depends on an experimental browser feature. An adapter
boundary allows swapping in an internal speech-to-text service later.

## 13. System design, scalability, security, cost, observability
Covered in depth in the ADRs and `DEPLOYMENT_SPEC.md`. In brief: clean seams isolate everything a
production migration would swap (engine, storage, ingestion, telemetry, model gateway); the
migration path to object storage / Postgres / ClickHouse / queues / OTel / OIDC / RBAC is
documented and *not* prematurely built. The LLM boundary strips all sensitive data; cost is
capped at zero by the free-model policy and tracked from provider metadata.

## 14. Design system
Two surfaces, one family (`docs/DESIGN.md`). Merchant: calm, warm (brand-ink + ZarinPal yellow),
insight-first, low cognitive load. Control Center: cooler slate + an operational blue accent,
denser and more precise, information-rich without Grafana clutter. Shared tokens, RTL-correct,
accessible; technical terms use progressive-disclosure tooltips (hover + keyboard focus + tap).

## 15. Limitations (honest)
Opportunity intervals are conservative/optimistic scenarios, not bootstrap CIs (labelled; low-peer
flagged). Telemetry is a hackathon JSONL store. Single-tenant, no enforced auth (queries already
scoped). GA4 live pull and paid-LLM calls are config-gated. Copilot paraphrase coverage is bounded.

## 16. Roadmap
Bootstrap CIs on peer gaps · seasonality/day-of-week analysis · interactive what-if simulator ·
GA4 live transport + two-window cross-source insights · durable telemetry + OTel · multi-tenant
auth/RBAC · additional source adapters (CRM, ads, accounting).
