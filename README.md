# Zarbin · زرین‌بین
### Merchant Intelligence **+** AI Operations for ZarinPal

Zarbin turns a ZarinPal payments dataset into **decisions**, across two connected surfaces that
share one deterministic intelligence platform:

- 🧑‍💼 **Merchant Workspace** — an insight-first dashboard that answers *"what's happening in my
  business, why, and what should I do?"* — no analytics knowledge required.
- 🛠️ **Control Center** — an operations surface (business / product / data / AI / engineering)
  that answers *"how is Zarbin itself doing?"* — platform health, product performance, AI
  operations & cost, data sources.

> The merchant sees a simple product. Underneath it is sophisticated — and every number is
> deterministic, traceable, and never invented by an AI.

---

## ▶ Live

**🔗 https://zarbin-nine.vercel.app**

| | |
|---|---|
| Merchant Workspace | log in via «فضای پذیرنده / مشتری» (demo gate: any phone, any 5-digit code) |
| Control Center | log in via «مرکز کنترل عملیات» — mints a signed, expiring ops session |
| Region | `fra1`, Vercel Python function + CDN-cached read API |
| Server-side latency | **p50 19 ms · p95 325 ms** (`Server-Timing: app;dur=…` on every response) |
| Whole dataset in the function | 2.06M sessions / 1.95M attempts as 63 MB of ZSTD parquet, queried in-process by DuckDB — no database server |

Deployment recipe and the constraints it works around: **[docs/DEPLOY_VERCEL.md](docs/DEPLOY_VERCEL.md)**.

## ▶ Or run it locally

```bash
uv run zarin
```
Then open **🔗 http://localhost:8630**

- **Merchant Workspace** → `http://localhost:8630/#/overview` (best first merchant: **M156**)
- **Control Center** → `http://localhost:8630/#/ops/overview`
  (or click **«مرکز کنترل»** in the top-right switch)

First run builds the Parquet marts (~33s), then serves. Windows/OneDrive: set `UV_LINK_MODE=copy`
(the `scripts/run.*` launchers and the VS Code task *"Run Zarbin Dashboard"* do this for you).
No API key and no network are required — the product runs fully offline on the deterministic engine.

---

## The major innovations

| | |
|---|---|
| **Paid-but-Unverified** | Money that settled at the bank but the merchant never verified — **real settled money, not an estimate.** Surfaced and quantified, not buried. |
| **Payment Rescue** | Sessions whose first attempt failed but a retry succeeded — recovered GMV, measured. |
| **Opportunity Engine** | Opportunity = **counterfactual** (gap vs matched peers × sessions × recovery fraction × median ticket of the lost outcome), **capped at realized GMV for every generator** in one shared guard. **Never** "lost revenue = Σ failed amounts." |
| **Explainable peers** | Peers matched by category + scale band + ticket band, ≥ pool size, suppressed when thin — with the *reason* shown. |
| **What Changed?** | Exact decomposition of a GMV move into sessions × conversion × ticket (LMDI, sums exactly). |
| **Evidence lineage** | Every number has a «محاسبه» button → definition, method, the **SQL that ran**, params, sample size, caveats, drill-through to source rows. |
| **Grounded Copilot** | Deterministic answers; an optional LLM only *rephrases*, and never on the answer path. The grounding guard binds every number to its **value and unit**, rejects rescaled figures, injected links/emails/phones, length inflation, **invented causality** and **flipped negations** (a free model really did turn «پرداخت تاییدنشده» into «تاییدشده» with every digit intact). Works offline. |
| **It answers the question you asked** | The copilot's understanding layer is a three-stage router — safety families → ordered exact rules → offline TF-IDF retrieval over a 13-intent bank — with four honest outcomes: answer, ask back, "I didn't understand, here are three I can answer", or refuse *and name the limit*. On 129 blind Persian questions this took **32% → 95%** right-question accuracy, misrouting **53% → 2%**, and answering questions it should refuse **38% → 5%**. See **[docs/RETRIEVAL.md](docs/RETRIEVAL.md)**. |
| **AI Operations** | Live AI quality separated into deterministic / grounding / language / usefulness — plus fallback, hallucination-risk, latency, tokens, **cost**. |
| **Voice** | Persian voice-to-text on both copilots (Web Speech, graceful fallback). |
| **Pluggable sources** | `DataSourceAdapter` — GA4 first (config-gated); web signals never confused with payment truth. |

---

## Architecture

```
             ┌──────────────────────────  one shared semantic layer  ──────────────────────────┐
 dataset ─►  DuckDB / Parquet marts ─► analytics · insights · peers ─► metric registry (evidence)
             (pipeline.py, db.py)              │                               │
                                               ├─► copilot.py (merchant) ─┐    │
 telemetry ◄─ obs.py (requests)                └─► ops_copilot.py (ops) ──┤    │
 telemetry ◄─ ai/telemetry.py (AI)                                         ▼    ▼
 sources/ (DataSourceAdapter: zarinpal=truth, ga4=gated)      ai/gateway.py (grounding guard)
                                                                    │  ▲ evidence-safe context
 control.py ─ platform · performance · ai-ops · sources             ▼  │ free-model policy
             ─────────────────  FastAPI: /api/* + /api/admin/*  ──►  [optional] OpenRouter (:free only)
                                        │
                          React + Vite + TS (RTL) ── Merchant surface  +  Control Center surface
```
Full rationale in **[docs/ADR/](docs/ADR/)** and **[docs/PLATFORM_BOOK.md](docs/PLATFORM_BOOK.md)**.

### Stack — kept, deliberately
Python · FastAPI · **DuckDB** / Parquet · React · Vite · TypeScript. We evaluated Next.js /
Postgres / ClickHouse / Redis / queues and **kept the stack**: it gives analytical correctness
(in-process columnar OLAP), one-command local reproducibility (no services, no keys), and clean
seams that isolate exactly what a production migration would swap. The multi-tenant migration path
(object storage → Postgres → ClickHouse → queues → OTel → OIDC/RBAC) is documented, not prematurely
built. See **[ADR-0001](docs/ADR/0001-architecture-stack.md)**.

---

## Preview

**Merchant Workspace**

| Overview | Funnel | What Changed? | Evidence drawer |
|---|---|---|---|
| ![](docs/screenshots/desk-overview.png) | ![](docs/screenshots/desk-funnel.png) | ![](docs/screenshots/desk-changes.png) | ![](docs/screenshots/desk-evidence.png) |

**Control Center**

| Platform | Product performance | AI operations | Data sources |
|---|---|---|---|
| ![](docs/screenshots/ops-overview.png) | ![](docs/screenshots/ops-performance.png) | ![](docs/screenshots/ops-ai.png) | ![](docs/screenshots/ops-sources.png) |

---

## Quick start

```bash
git clone https://github.com/ladekarl1234-commits/zarbin-merchant-intelligence.git
cd zarbin-merchant-intelligence
uv run zarin                     # builds marts on first run, serves http://localhost:8630
```
Rebuild the frontend: `cd frontend && npm ci && npm run build` (outputs to `zarin/static`).
Docker: `docker compose up`.

### 60-second demo path
1. **Overview (M156)** — top opportunity is **Paid-but-Unverified** (real settled money) with an evidence drawer.
2. **What Changed?** — decompose a GMV move into traffic × conversion × ticket.
3. **Ask** — "چرا فروشم کم شد؟" · try the 🎙️ mic.
4. Switch to **مرکز کنترل** → **AI operations**: grounded rate, fallback, cost (₴0, free-model policy).
5. **Data sources** — ZarinPal = truth; GA4 = ready-to-connect.

---

## Environment variables
`OPENROUTER_API_KEY` (optional; enables the `/api/copilot/polish` rephrasing pass — never the
answer path) · `OPENROUTER_MODEL` (default `nvidia/nemotron-3-super-120b-a12b:free`, chosen by
[measurement](zarin/ai/models.py), **free-model policy enforced**) ·
`GA4_PROPERTY_ID` + `GOOGLE_APPLICATION_CREDENTIALS` (optional GA4) ·
`ZARIN_ADMIN_TOKEN` (set → Control Center API requires `X-Admin-Token`) ·
`ZARIN_PORT` (8630) · `ZARIN_HOST` · `ZARIN_DATA_PATH` · `ZARIN_MARTS_DIR` · `ZARIN_TELEMETRY_DIR`.
No secrets are committed; the dataset is git-ignored and absent from history.

## Testing
```bash
uv run pytest -q                        # 180 tests
uv run ruff check .                     # lint
cd frontend && npm run build            # tsc (strict) + vite
uv run python -m zarin.ai.eval          # copilot eval: deterministic / grounding / refusal
uv run python -m zarin.ai.eval.retrieval -v   # intent routing, before/after, two blind sets
uv run python pipeline/calibrate_nlu.py       # leave-one-out calibration of the router constants
```
CI: [.github/workflows/ci.yml](.github/workflows/ci.yml) (Python + frontend jobs).

---

## Measured results — before and after

Full record with every reproduce-command: **[docs/EVALUATION.md](docs/EVALUATION.md)**.

| | before | after |
|---|---:|---:|
| Right-question accuracy, 129 blind Persian questions | 0.318 | **0.954** |
| Answered a *different* question than the one asked | 0.528 | **0.022** |
| Answered a question it should have refused | 0.375 | **0.050** |
| Deployed numbers recomputed from the raw dataset | — | **240/240 exact** |
| Server-side latency p50 / p95, 71 live endpoint cases | — | **19 ms / 325 ms** |
| Non-2xx across the full live probe | — | **0/71** |
| Tests | 137 | **180** |

The "before" is not a description of the old router — it is the old router, executed on the
same questions by the same scorer (`zarin/ai/eval/retrieval.py`). The question sets were
written by labellers denied access to the repository and double-labelled with disagreements
dropped. Reproduce: `uv run python -m zarin.ai.eval.retrieval -v`.

## Independent expert review

This repository carries its own audit. Commit `75de6bb` was evaluated by a panel of **15 specialized
expert agents** — architecture, code quality, data & analytics correctness, statistical methodology,
security, reliability, scalability, product, business viability, UX, design, accessibility, AI
grounding, testing, plus a lens scoring the competition's own 300-point rubric. **Critical** and
**high** findings were then re-examined by a **separate verification agent** before being recorded —
43 of the 44 were verified (**43 confirmed, 0 refuted**; ZB-044 was missed by the per-lens cap).
58 agents ran in total. The record was then audited itself, which corrected four figures in it and
surfaced one further defect ([ZB-120](docs/EXPERT_REVIEW_ISSUES.md#zb-120)).

| | |
|---|---|
| Mean dimension score | **73.4 / 100** (median 73, range 61–82) |
| Competition rubric | **236 / 300** (actionability 76/90 · correctness 58/75 · depth 41/60 · UX 36/45 · technical 25/30) |
| Findings documented | **120** — 119 from the panel (5 critical · 39 high · 56 medium · 19 low) + ZB-120, found while auditing the record |
| Strongest dimensions | code quality **82** · data correctness **82** · architecture **80** |
| Weakest dimensions | accessibility **61** · security **66** · scalability **66** |

The headline result is a **claim-vs-enforcement gap**: the analytical core is genuinely strong (grain
discipline verified live, LMDI exact to ~1e-15, acyclic layering, deterministic-first AI), but several
guarantees are stated unconditionally in the docs while being only partly enforced in code — the
realized-GMV cap lives only in `_gap_card` so three opportunity generators are uncapped (one live card
reaches 107% of a merchant's realized GMV), the evidence drawer prints a formula the code no longer
uses, the "the LLM may only rephrase" guard inspects digits only, and one card is outright
non-deterministic (`ntile` without a tiebreaker returns different money on identical calls). Those,
plus the absence of authentication and the accessibility conformance gaps, are the work queue.

- 📋 **[docs/EXPERT_REVIEW.md](docs/EXPERT_REVIEW.md)** — the record: method, panel, scores, rubric
  mapping, per-lens verdicts, priority queue, final assessment and the review's own limitations.
- 🐞 **[docs/EXPERT_REVIEW_ISSUES.md](docs/EXPERT_REVIEW_ISSUES.md)** — all 119 findings, each with a
  stable ID (`ZB-001`…`ZB-119`), location, observed evidence, impact, recommended fix and effort.
- 🧾 **[docs/expert_review_findings.json](docs/expert_review_findings.json)** — the raw structured
  results, machine-readable (regenerate the documents with `pipeline/gen_expert_review.py`).

*(Excluded from that round by request: the demo video and deployment/hosting/CI-CD — it evaluates the
software itself, so it is not a production-readiness verdict.)*

## Documentation
- **[memory.md](memory.md)** — engineering continuity: invariants, AI rules, gotchas.
- **[docs/PLATFORM_BOOK.md](docs/PLATFORM_BOOK.md)** — why this exists and why it's built this way.
- **[docs/ADR/](docs/ADR/)** — stack · deterministic-vs-LLM · OpenRouter free policy · source adapters.
- **[docs/DEPLOYMENT_SPEC.md](docs/DEPLOYMENT_SPEC.md)** — local + production-shaped deployment.
- **[docs/EXPERT_REVIEW.md](docs/EXPERT_REVIEW.md)** — 15-agent expert audit: scores, findings, assessment.
- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** · **[docs/ANALYTICS.md](docs/ANALYTICS.md)** ·
  **[docs/DATA_AUDIT.md](docs/DATA_AUDIT.md)** · **[docs/DESIGN.md](docs/DESIGN.md)** ·
  **[CONTRIBUTING.md](CONTRIBUTING.md)** · **[docs/JURY_REVIEW.md](docs/JURY_REVIEW.md)** ·
  **[docs/VALIDATION.md](docs/VALIDATION.md)**.

## Limitations (honest)
Opportunity intervals are scenarios, not bootstrap CIs (labelled; low-peer flagged). Telemetry is a
hackathon JSONL store. Single-tenant, no enforced auth (queries already scoped). GA4 live pull and
paid-LLM calls are config-gated. See PLATFORM_BOOK §15 for the full list.

---
*IRR (rial) throughout · Persian-first RTL · ZarinPal brand · deterministic, traceable, grounded.*
