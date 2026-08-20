# Expert Panel Review — full issue register

All **119 findings** from the 15-lens expert panel on commit `75de6bb`, most severe
first, each with a stable ID so it can be tracked and fixed individually.
`Verification` is the independent second-agent verdict; every critical/high finding went through
that pass (medium/low did not). See [EXPERT_REVIEW.md](EXPERT_REVIEW.md) for the process, scores
and overall assessment.

**Counts:** 5 critical · 39 high · 56 medium · 19 low

---

## CRITICAL severity

### ZB-001 · No authn/authz on any merchant data endpoint; tenant scoping is a client-supplied parameter

**Lens:** `security` · **Severity:** CRITICAL · **Effort:** large · **Verification:** CONFIRMED

- **Where:** zarin/api.py:97-234 (all /api/* merchant routes); frontend/src/ctx.tsx:29-40 (merchant picker); frontend/src/pages/Login.tsx:83
- **Observed:** `curl -s http://localhost:8630/api/meta` returns all merchants with GMV/session counts unauthenticated. `curl '.../api/evidence/sessions?m=M156&limit=2'` returns session-level rows (session_key, amount, outcome, PSP, statuses) for an arbitrary merchant key. The only gate is Login.tsx, which is pure frontend state: the OTP form's `onSubmit` calls `onLogin(target)` with no validation (even an empty code proceeds) and writes `sessionStorage.zb_ws`; no request ever carries a credential. README.md:144 describes this as "Single-tenant, no enforced auth (queries already scoped)" — scoping by an attacker-controllable `m` parameter is not authorization.
- **Impact:** Anyone who can reach the port reads every merchant's revenue, conversion, customer counts and per-session payment rows, and can enumerate the whole merchant book via /api/meta. For a payments product this is the disclosure that matters most, and the README wording understates it.
- **Recommended fix:** Issue a session token at login that binds a merchant_key (or an operator role), derive `m` server-side from that claim instead of the query string, and 403 any mismatch. Until then, state plainly in README §Limitations and on the login screen that the API is unauthenticated and every merchant is readable.
- **Verifier's note:** Substance is real and reachable exactly as described — every factual claim in the finding checks out, including the empty-OTP path and the client-supplied `m`. I'd assign High rather than Critical for this artifact, on three mitigations the finding omits:

1. It is not undocumented, and README:144 is not the only place it is described. docs/DEPLOYMENT_SPEC.md:73-75 states it plainly in a production-gap table — "AuthN | none (single-tenant) | OIDC; sessions" and "AuthZ | queries already merchant-scoped | RBAC (merchant / operator / ZarinPal-internal); tenant-scoped queries enforced at the boundary" — plus :87-88 on the token being unset on the loopback demo. So this is a declared design limit of a hackathon/evaluator build, not a silent hole. The finding's "README understates it" is fair about that one line but wrong that the repo understates it overall.
2. Default bind is loopback: zarin/config.py:13 `HOST = os.environ.get("ZARIN_HOST", "127.0.0.1")`, and docker-compose.yml publishes `127.0.0.1:8630:8630` with the comment "bind-publish to localhost only: the app has no auth (evaluator mode)". "Anyone who can reach the port" is true, but by default nobody off-host can. (Caveat: the Dockerfile sets `ENV ZARIN_HOST=0.0.0.0`, so `docker run` without compose does expose it on all interfaces — that is the one path where this escalates.)
3. The dataset is the anonymized challenge extract (`other_challenge_data.csv.gz`, merchant keys M18/M156/M250, no PII/PAN in the evidence rows — card identity is noted as absent), not live production merchant records.

Critical is the right severity the moment this is deployed off loopback or pointed at real merchant data; as the repo stands today, High. The correct fix location is the same one the finding names: a dependency on the merchant routes that derives `m` from the session instead of trusting the query param — `_check_merchant` should become `_authorize_merchant`.

### ZB-002 · Process-wide RLock serializes every DuckDB query — hard concurrency ceiling

**Lens:** `scalability` · **Severity:** CRITICAL · **Effort:** small · **Verification:** CONFIRMED

- **Where:** zarin/db.py:14,63 (`_lock = threading.RLock()`, `with _lock:` in `q()`)
- **Observed:** 8 parallel `curl /api/customers?m=M156`: individual `time_starttransfer` 0.38/0.49/0.64/0.78/0.98/1.25/1.31/1.38 s, wall 1,535 ms — a perfectly linear staircase matching 8 × the ~160 ms solo cost. Every `q()`/`q1()` holds one global lock, and every FastAPI route is a sync `def`, so the anyio threadpool provides no real parallelism.
- **Impact:** Throughput ceiling is ~6 req/s for `/api/customers` and ~2.8 req/s for `/api/insights` on M250, on any hardware — adding cores or replicas of the app inside one process cannot help. At 10x concurrent merchants the p95 becomes multi-second even though each query is fast. This, not "single-process marts/telemetry" as ADR-0001 claims, is the actual first bottleneck.
- **Recommended fix:** DuckDB supports concurrent reads from one database via independent cursors. Replace the global lock with a `threading.local()` holding `_con.cursor()` per thread (lock only the one-time `connect()`), and set an explicit `SET threads` so N concurrent queries don't each try to use all 8 cores.
- **Verifier's note:** Substance CONFIRMED; severity overstated — I'd assign MEDIUM, not Critical, and the root-cause attribution is wrong.

What holds: the process-wide serialization is real, reachable on every endpoint, and the ~6 req/s ceiling reproduces (measured 6.5 req/s for 8x /api/customers). The staircase and the ~160 ms solo figure are accurate.

What does not hold:

1. The lock is not the bottleneck — CPU saturation is. Neutering `_lock` entirely moved 1278 ms to 1129 ms (12%). The correct fix (per-thread `con.cursor()`, no lock) gave 1241 ms to 1054 ms — ~15%, not the 8x the "hard ceiling" framing implies. DuckDB is already saturating the box: `current_setting('threads')` = 8, and solo cost is 163 ms at 8 threads vs 409 ms at 1 thread. Adding per-cursor thread tuning (`SET threads=2`) made it *worse* (1568 ms). There is no idle parallelism for lock removal to unlock.

2. "on any hardware — adding cores... cannot help" is false. The 163 ms vs 409 ms measurement shows DuckDB's intra-query parallelism already converts cores into latency today, and would continue to. Replicas across *processes* also scale fine here — the marts are read-only parquet views (db.py:29-31), so multi-process is trivially safe; only the in-process claim is a tautology.

3. The implied remedy is actively dangerous. With the lock removed, 8/8 concurrent calls raised `KeyError('customers')` — `connect().execute(...)` returns the shared connection as its own cursor, so concurrent threads interleave `execute()` / `.description` / `.fetchall()` and read each other's result sets. The RLock is load-bearing for correctness, not gratuitous overhead. Anyone "fixing" this finding by deleting the lock ships silent cross-request data corruption — on a payments dashboard, where one merchant would see another's rows. That risk is worth flagging louder than the throughput issue.

Fair characterization: a documented single-process ceiling worth a `ponytail:`-style comment naming per-thread cursors as the upgrade path, not a critical architectural defect. ADR-0001's "single-process marts/telemetry" framing is closer to correct than the finding allows — the first real bottleneck is that one process is CPU-bound on DuckDB, which is the same conclusion.

No repo files were modified; all probes ran from the scratchpad directory.

### ZB-003 · 37% of merchants see an empty dashboard; the empty state calls a broken funnel "good news"

**Lens:** `business` · **Severity:** CRITICAL · **Effort:** medium · **Verification:** CONFIRMED

- **Where:** zarin/insights.py:135 (generate) + frontend/src/pages/Overview.tsx:77-80 (Empty state)
- **Observed:** Ran generate() for all 343 merchants over the full period: 126 (37%) return zero cards, 193 (56%) return zero opportunity cards. Card-count histogram: {0:126, 1:89, 2:42, 3:40, 4:29, 5:13, 6:2, 7:2}. Thresholds cause it — MIN_SESSIONS_INSIGHT plus a ≥500-session peer pool (peers.py:17) that only 81 of 343 merchants clear, and ≥5 peers required per gap card. Worse, the empty state reads «فرصت قابل اتکایی پیدا نشد … این خودش خبر خوبی است» — yet M89 (63 sessions, 0% conversion, 78% no-attempt) and 12 other zero-card merchants with ≥50 sessions and <25% conversion get exactly that message.
- **Impact:** The product has nothing to say to the majority of a PSP's merchant base — the population that most needs it. Those merchants open it once and never return, so weekly-active adoption collapses to the head. Telling a merchant with a 0%-conversion integration that silence "is good news" is an active false negative that costs trust the first time they discover it.
- **Recommended fix:** Split the empty state in two: a genuine all-clear (real volume, no gap) versus "we cannot benchmark you yet — here is your own funnel, and here is your absolute no-attempt/in-bank rate against a fixed platform-wide floor". Add an absolute-threshold card (e.g. no_attempt_rate > 40%) that needs no peer group, so a broken integration is always named regardless of scale.
- **Verifier's note:** Substance is real and reachable; severity is overstated — I'd assign HIGH, not critical. Two corrections to the claim: (1) numbers drift by one bucket (127 zero-card / 87 one-card here vs the claimed 126/89; the 193 zero-opportunity, 81/343 peer pool and 13 low-conversion zero-card merchants match exactly), and (2) "empty dashboard" is inaccurate — the Overview page still renders the KPI row, the paid-unverified callout and the daily trend chart for these merchants (M89's /api/overview returns 63 sessions and a populated `daily` array), and the funnel page still shows the 78% no-attempt stage. What is empty is the "مهم‌ترین فرصت‌های شما" section. The genuine defect is the copy: the empty state conflates "no evidence" with "no problem" and tells a 0%-conversion merchant that silence is good news. That is a one-line, no-schema fix (branch the Empty body on sessions < MIN_SESSIONS_INSIGHT or peer-group insufficiency), which is another reason it does not read as critical.

### ZB-004 · Grounding guard is digit-only: invented causality and advice pass verbatim

**Lens:** `ai-grounding` · **Severity:** CRITICAL · **Effort:** medium · **Verification:** CONFIRMED

- **Where:** zarin/ai/gateway.py:56-60 (is_grounded), :99 (only gate before returning LLM text)
- **Observed:** With a fake provider returning «افت فروش شما به دلیل کلاهبرداری کارمندانتان بوده است؛ فوراً حساب را ببندید.» against det text «نرخ تبدیل ۵۴٫۵٪ بود.», gateway.explain returned source=llm, grounded=True, fallback=False, quality_flags=[] and answer_fa = the fabricated text. The user question is echoed raw into the LLM prompt (gateway.py:87 «پرسش کاربر: {question}»), giving a direct injection path to that output. ADR-0002:6-7 names invented causality as the top risk; nothing in code mitigates it.
- **Impact:** A merchant can be shown a fabricated cause, attribution or instruction carrying the chip «با کمک هوش مصنوعی» and the note «این پاسخ بر پایه اعداد قطعیِ موتور تحلیلی است» — a false assurance of determinism on a fintech surface, with no telemetry flag emitted.
- **Recommended fix:** Add a non-numeric containment check before accepting comp.text: reject when it introduces content-bearing tokens absent from the deterministic answer (token-overlap / novel-noun threshold), reject output longer than ~1.5x the deterministic text, and stop sending the raw user question (send intent + computed answer only, which safe_context already assembles). Flag rejections as ungrounded_prose.
- **Verifier's note:** Substance is real and unexaggerated; I'd rate it high rather than critical. The only gap in the "critical" framing is reachability gating: the LLM branch runs only when `OPENROUTER_API_KEY` is set (`zarin/config.py:26` → `provider.default_provider()` returns None otherwise, README:116 calls the key "optional"), so the default/judge deployment is deterministic-only and unaffected. Whenever a key is configured — the intended product configuration — it is fully live, with `quality_flags=[]` so telemetry emits no signal at all. Cheapest fix consistent with the existing design: also fall back when the LLM text contains causal/imperative markers absent from the deterministic text, or (lazier and stronger) compare token overlap and fall back below a threshold — one guard in `is_grounded`, which both call sites already route through.

### ZB-005 · Peer percentile happy path has zero coverage — only the suppressed branch is tested

**Lens:** `testing-qa` · **Severity:** CRITICAL · **Effort:** medium · **Verification:** CONFIRMED

- **Where:** zarin/peers.py:100-118 (and 52-54); tests/test_insights_peers.py:13-19
- **Observed:** Coverage shows peers.py:105-111 and 52-54 never execute. Every fixture merchant is below the 500-session pool floor, so test_small_peer_pool_suppresses_benchmarks only ever exercises the `suppressed=True` early-return at peers.py:103/107. The computation that actually ships — `better = sum(1 for v in vals if (mine > v) == higher_better and mine != v)` (peers.py:109), the p25/p50/p75 quantiles, and the level fallback scale+ticket→scale→category (the `>= PREFERRED_PEERS` break at peers.py:52-54) — is never run. Live confirmation: `curl /api/peers?m=M156` returns n=5, level=category, sufficient=true, percentiles [conv 60, first_try_conv 60, no_attempt_rate 60, inbank_abandon_rate 20, recovery_rate 60].
- **Impact:** Inverting `higher_better` for a cost metric (e.g. no_attempt_rate) would tell a merchant they are in the 80th percentile when they are in the 20th, and the entire suite still passes. Peer benchmarking is a headline surface and the failure is silently plausible-looking.
- **Recommended fix:** Add a synthetic peer cohort (≥8 merchants with ≥500 sessions each) to conftest, or call `peers.benchmarks` against injected `merchant_stats`/`merchant_daily` fixtures, and assert exact percentiles for a hand-computed cohort including one higher_better=True and one higher_better=False metric plus the three-level group fallback.
- **Verifier's note:** Substance is real and reachable; severity is overstated. I'd assign HIGH, not CRITICAL.

There is no live defect: the current polarity table is correct (`no_attempt_rate`/`inbank_abandon_rate` → `higher_better=False`) and peers.py:109 `(mine > v) == higher_better` computes the right rank for both polarities — for a cost metric it counts peers worse than you, which is what a "60th percentile" badge should mean. M156's shipped numbers are correct today. So this is a latent-risk / zero-regression-protection finding, not a wrong number in production, which is what separates high from critical.

What keeps it high rather than medium is the mutation result: the failure mode is silent, plausible-looking, user-facing, and the suite provably does not catch it. The fix is small — one fixture merchant group above the 500-session floor (or a direct unit test on the ranking expression with a synthetic peer list, which needs no fixture change at all) would cover peers.py:105-118 and kill the mutation.

Two minor corrections to the claim's wording, neither affecting the verdict: (a) line 52 itself is covered (the `if` is evaluated, always false); only the 53-54 body is dead. (b) The claimed curl reproduces only on the default period — `?m=M156&f=2026-01-01&t=2026-01-31` returns `sufficient:false` with all rows suppressed, because `peer_period_rates`' `HAVING sum(sessions) >= 100` drops the pool below MIN_PEERS for that window. The happy path is still plainly reachable on the default period.

Files: C:\Users\pro\OneDrive\Desktop\zarinpal\zarin\peers.py, C:\Users\pro\OneDrive\Desktop\zarinpal\tests\test_insights_peers.py, C:\Users\pro\OneDrive\Desktop\zarinpal\tests\conftest.py. Nothing in the repo was modified; the mutation probe lives at C:\Users\pro\AppData\Local\Temp\claude\C--Users-pro-OneDrive-Desktop-zarinpal\bf8c8e22-2712-4ce0-8613-d1c56f309e84\scratchpad\mutplug.py.

## HIGH severity

### ZB-006 · Realized-GMV cap applied to only one of four opportunity generators — a card claims 108% of the merchant's entire sales

**Lens:** `rubric-official` · **Severity:** HIGH · **Effort:** small · **Verification:** CONFIRMED

- **Where:** zarin/insights.py:220-221 (high_value_friction); same gap at :190 (recovery_gap) and :256 (repeat_gap); cap lives only at :86-93 inside _gap_card
- **Observed:** Live: /api/insights?m=M21 returns high_value_friction impact_low 2,356,248,967 / impact_high 4,712,497,933 with capped=None, while /api/overview?m=M21 reports gmv 4,373,353,280 — the "opportunity" is 108% of realized six-month GMV. Surveying 60 merchants, 17/116 rial-denominated opportunity cards exceed 20% of realized GMV; the three uncapped kinds account for the top outlier. tests/test_insights_peers.py::test_opportunity_capped_at_realized_gmv exercises only the _gap_card path, which is why this survived.
- **Impact:** The headline number on an InsightCard (rendered large by InsightCard.tsx:32) can exceed everything the merchant actually sold, with no «سقف واقع‌بینانه» chip. One implausible figure discredits the eight credible cards beside it, and this is exactly the "Σ failed amounts" failure mode the README claims the product avoids.
- **Recommended fix:** Lift the cap out of _gap_card into the ranking loop at insights.py:303-309: after each card is built, clamp impact_low/mid/high to period GMV and set capped=True so the existing warning chip fires. One shared guard covers all present and future generators.
- **Verifier's note:** Severity "high" is fair; I would keep it. Two facts beyond the original claim push it up rather than down. (1) It violates an explicitly documented product invariant, not just an aesthetic expectation: README.md:41 states the Opportunity Engine is "capped at realized GMV", and memory.md:38 / CONTRIBUTING.md:78 restate "NEVER lost revenue = Σ failed amounts" as a hard rule. (2) The uncapped figure escapes the card surface — zarin/copilot.py:120 interpolates impact_low/impact_high into assistant answers, where there is no `capped` chip at all, so the implausible number reaches the chat path with even less framing than the card.

Mitigating, but not enough to downgrade: it is a plausibility/credibility defect in a presented estimate, not data corruption, a crash, or a security or money-movement bug. Nothing downstream consumes impact_high as a financial commitment.

One fairness correction to the survey framing: paid_unverified (0.93 of GMV for M21) also carries capped=None, but that card is a factual sum of settled-but-unverified amounts (impact_label_fa explicitly says "not an estimate"), so it is legitimately uncapped and should not be counted as an overclaim. Excluding it, the estimate-bearing overclaims are ~15 of ~112. The substance is unchanged.

Fix note: root cause is one location, not four. All four generators converge in generate() before the ranking loop at :303-309, which already iterates every card and reads impact_high. Applying the realized-GMV clamp and the `capped` flag there covers all kinds at once (skipping cards with impact_is_count, which are transaction counts not rials, and paid_unverified, which is a realized amount) — a smaller diff than copy-pasting the cap into three call sites, and it stays correct for any generator added later. The existing test should then be extended to assert through generate() rather than _gap_card directly, since calling the helper in isolation is what let this survive.

### ZB-007 · Evidence drawer prints two contradictory formulas for the same opportunity number

**Lens:** `rubric-official` · **Severity:** HIGH · **Effort:** small · **Verification:** CONFIRMED

- **Where:** zarin/registry.py:74-76 (Metric "opportunity"), rendered by frontend/src/components/EvidenceDrawer.tsx; README.md "Opportunity Engine" row repeats it
- **Observed:** Live evidence payload for M156/inbank_gap shows formula "excess_rate × sessions × conv(own) × median_ticket(own)" and caveat "بازه از خط پایه میانه (کف) و چارک برتر (سقف) همتایان ساخته می‌شود" — directly above the sql field of the same object, which reads "(0.3527 − 0.2651) × 55940 × [0.5 … 0.75 … 1.0] × 40,071,150". The real code (insights.py:79-82) uses no conv(own) and no p25/p50 band; the band is a fixed recovery fraction.
- **Impact:** Traceability is the product's core claim. A judge who opens the drawer to check how 147.3B was derived reads a formula that does not reproduce the number, and a caveat describing a band construction that was abandoned. It also understates the estimate's aggressiveness (a 100% gap-closure ceiling reads as a peer top-quartile ceiling).
- **Recommended fix:** Rewrite the opportunity Metric's formula_fa to "(your_rate − peer_median) × sessions × recovery_fraction[0.5…1.0] × median_ticket(lost outcome)" and replace the caveat with the honest one already in the card label; fix the matching README row.
- **Verifier's note:** Substance is fully real and reachable; I'd assign medium-high rather than high. Nothing miscomputes — the shipped number is correct and the true method string sits in the same drawer a few lines below the wrong one — so no merchant acts on a bad figure. But it lands squarely on the product's flagship traceability surface, where a judge comparing the formula line to the number gets a mismatch, and the caveat actively misrepresents the estimate's ceiling (100% gap closure sold as a peer top-quartile bound). Fix is four stale strings: zarin/registry.py:74-76 and README.md:41; no logic change.

### ZB-008 · Chat is the landing surface but its regex router misses questions the engine can already answer

**Lens:** `rubric-official` · **Severity:** HIGH · **Effort:** medium · **Verification:** CONFIRMED

- **Where:** zarin/copilot.py:39-131 (_plan); landing page frontend/src/pages/CopilotPage.tsx (docs/screenshots/rd-chat.png)
- **Observed:** Live /api/copilot?m=M156: «کدام درگاه بدترین عملکرد را دارد؟» → intent=fallback, despite insights._psp_card computing exactly that (PSP-03 20.5% vs PSP-04 59.4% for this merchant). «چطور نرخ تبدیلم را بالا ببرم؟» → fallback, despite the priorities intent existing. «بهترین روز هفته برای کمپین چیست؟» → fallback. «فروش من چقدر بوده؟» → fallback. The fallback text then re-lists the same six canned questions shown on the empty state.
- **Impact:** The redesign makes chat the front door for a non-analyst merchant. Four of seven natural Persian phrasings I tried dead-end into a generic KPI paragraph, and the one about gateways is answerable — the merchant is told nothing while the answer sits one card away.
- **Recommended fix:** Add a psp/gateway intent routing to _psp_card, widen the priorities regex to intent verbs (بالا ببرم|بهتر کنم|افزایش|رشد|چطور), and make the fallback do keyword-overlap against metric names in the registry before giving up, so it names the closest available analysis instead of the canned list.
- **Verifier's note:** Substance is real and I reproduced it plus two extra gateway phrasings that also miss. One detail is overstated: «فروش من چقدر بوده؟» routes to fallback but the fallback paragraph literally answers it (فروش موفق ۱٫۹۵ هزار میلیارد ریال …), so it is 3 genuine dead-ends out of the 4 cited, not 4. Also there is no day-of-week analytic anywhere in the engine, so «بهترین روز هفته» is a missing feature rather than a routing miss — the only case where an existing answer is truly withheld is the PSP/gateway one. Severity I'd assign: medium-high rather than high. It is a coverage gap on the front door, not a wrong number or a broken path; the fallback still returns correct KPIs and points at the six working intents, and the PSP answer is one click away on the overview card. What keeps it above low is that chat is the default landing page and the engine demonstrably already knows the answer.

### ZB-009 · API contract crosses the biggest seam untyped and hand-mirrored

**Lens:** `architecture` · **Severity:** HIGH · **Effort:** medium · **Verification:** CONFIRMED

- **Where:** frontend/src/api.ts:1-158 and zarin/api.py (all routes)
- **Observed:** No FastAPI route declares a response_model. Live check of http://localhost:8630/api/openapi.json returns `components.schemas` = ['HTTPValidationError','ValidationError'] only, and `/api/overview` 200 response schema is `{}`. The 158 lines of TypeScript types in api.ts are hand-maintained, self-described as "mirrors zarin/api.py responses".
- **Impact:** The FE/BE boundary has no machine-checked contract. Renaming or dropping a backend field (e.g. `paid_unverified_amount`, `conv_drivers`) compiles clean on both sides and surfaces as undefined at runtime in the UI. This is the seam most exercised by feature growth, and it is the only one with no verification at all.
- **Recommended fix:** Add Pydantic response models (or TypedDicts via `response_model`) to the ~15 routes, then generate api.ts types from /api/openapi.json with openapi-typescript in the build. Even models on just overview/insights/funnel/peers/changes would cover most of the drift risk.
- **Verifier's note:** Substance is real and reachable, but severity is overstated — I'd assign MEDIUM, not high. Two corrections: (1) "no verification at all" is wrong for the two fields cited as examples — tests/test_metrics.py:32 asserts a["paid_unverified_amount"] == 50000, tests/test_insights_peers.py:80 asserts ov["kpis"]["paid_unverified_amount"], and tests/test_metrics.py:88-94 asserts "reversed_rate" in ch["conv_drivers"] and that its values sum to the conv delta. Renaming or dropping either of those specific fields breaks pytest, so it does not "compile clean on both sides". (2) All drift that actually exists today (compare, period) is in the benign direction — extra backend fields the FE ignores — so there is no live user-visible bug, and frontend/package.json runs `tsc --noEmit` on build, which catches FE-internal inconsistency (just not FE-vs-BE). The gap is a genuine maintainability hole on the most-churned seam, worth a generated-types or response_model pass, but it is not a defect users can hit right now.

### ZB-010 · Hardcoded data fact in the API layer contradicts the computed metric on the same page

**Lens:** `architecture` · **Severity:** HIGH · **Effort:** small · **Verification:** CONFIRMED

- **Where:** zarin/api.py:256 (rules_fa) vs zarin/api.py:243-246 (anomalies)
- **Observed:** `/api/quality` computes `anomalies.verified_wo_ok_try` live and also returns a Persian prose rule containing the literal "۲۸ جلسه Verified بدون تلاش Verified". I verified both against the live marts: `wo_verified_try`=28, `wo_ok_try`=1. frontend/src/pages/QualityPage.tsx:52 renders the computed 1 and line 61 renders the hardcoded 28 in the list directly below it.
- **Impact:** The Data Quality page — whose entire pitch is analytical honesty — shows "۱ جلسه Verified بدون تلاش موفق" immediately above "۲۸ جلسه Verified بدون تلاش Verified". Both are individually true under different definitions, but the labels are near-identical and one is a literal that will silently go stale on any new dataset. `/api/quality` is also the one endpoint that calls no `evidence()` at all and writes its own SQL in the API layer.
- **Recommended fix:** Derive both counts in the query (they differ only by whether 'Paid' counts as an ok try), register them as two distinct metrics in registry.py with distinct name_fa, and interpolate the computed values into rules_fa instead of hardcoding 28.
- **Verifier's note:** Substance is fully real and reachable — the two contradictory-looking numbers render on the same page in adjacent cards, and the 28 is a frozen literal that will silently go stale on any new dataset while the 1 next to it re-computes. I'd assign medium rather than high: no analytics output is wrong (both figures are true under their respective definitions), nothing on a money or security path is affected, and there is no data loss or incorrect aggregate — the harm is user confusion on the honesty page plus guaranteed future staleness. Fix is to drop the literals from rules_fa and interpolate from a second computed anomaly (e.g. add `verified_wo_verified_try` to the anomalies q1 and format the rule from it), which also removes the only raw-SQL-in-API-layer endpoint's last hardcoded fact.

### ZB-011 · Metric registry — the declared single source of truth — has drifted from the code it documents

**Lens:** `code-quality` · **Severity:** HIGH · **Effort:** small · **Verification:** CONFIRMED

- **Where:** zarin/registry.py:74-76 vs zarin/insights.py:50-131
- **Observed:** `Metric("opportunity", …)` declares formula `excess_rate × sessions × conv(own) × median_ticket(own)` and the caveat «بازه از خط پایه میانه (کف) و چارک برتر (سقف) همتایان ساخته می‌شود». The shipped `_gap_card()` computes `(your_rate − peer_median) × sessions × recovery_fraction[0.5/0.75/1.0] × median_ticket_of_lost_outcome` and its own docstring explicitly rejects the p25↔p50 band as «spuriously narrow». I fetched `/api/insights?m=M156`: the *same* evidence payload renders the stale `formula`/`caveats` directly next to the correct `sql` string, so the drawer contradicts itself in one panel.
- **Impact:** The evidence drawer is the product's core trust affordance; it now shows a formula the engine does not run and a caveat describing an abandoned methodology. The registry's `REGISTRY[metric_id]` lookup gives no structural pressure to keep the two in sync, so every future methodology change repeats this.
- **Recommended fix:** Update the `opportunity` Metric's `formula_fa`/`caveats` to the recovery-fraction band, and add a test in `tests/test_insights_peers.py` asserting the registry formula string is a substring of / consistent with the `sql` the card emits.
- **Verifier's note:** Substance fully confirmed and reachable in the default UI path (any merchant with a >2pp no_attempt/inbank gap vs peer median). I would assign medium-high rather than high: no displayed number is wrong — impact_low/mid/high are computed correctly by the code — the defect is stale prose rendered next to correct method text. It is still a genuine self-contradiction inside the product's core trust affordance, and a reviewer who reads the drawer carefully loses confidence in every other panel, so it is well above cosmetic. Cheapest fix in keeping with the module's own claim of being the single source of truth: correct registry.py:74-76 to `excess_rate × sessions × recovery_fraction[0.5…1.0] × median_ticket(lost outcome)` and replace the p50/p75 caveat with the scenario-band wording already in the `_gap_card` docstring; optionally add one assert in tests/test_insights_peers.py that `REGISTRY["opportunity"].formula_fa` mentions `recovery_fraction`, so the next methodology change trips a test instead of shipping.

### ZB-012 · `insights.generate()` is a 181-line C901=20 function whose shape contradicts the documented extension pattern

**Lens:** `code-quality` · **Severity:** HIGH · **Effort:** medium · **Verification:** CONFIRMED

- **Where:** zarin/insights.py:135-315
- **Observed:** `uv run ruff check --select C90 --config 'lint.mccabe.max-complexity=8'` reports `_plan` 14 (copilot.py:39), `_plan` 18 (ops_copilot.py:32) and `generate` **20** (insights.py:135). Four cards are extracted helpers (`_gap_card`, `_psp_card`, `_change_alert`) but five — `paid_unverified`, `recovery_gap`, `high_value_friction`, `repeat_gap`, `concentration` — are inline dict literals with embedded SQL and multi-line Persian copy, interleaved with the ranking logic at 301-314. CONTRIBUTING.md:47 tells a new engineer «add a `_…_card()` in zarin/insights.py», which describes only 4 of the 9 shipped cards.
- **Impact:** Adding the tenth insight means editing the same function that ranks all of them; a mistake in one card's dict silently reorders or drops others. The documented onboarding instruction does not match what the file actually looks like, so a new engineer either follows the doc (inconsistent with neighbours) or copies the neighbours (inconsistent with the doc).
- **Recommended fix:** Extract the five inline blocks into `_paid_unverified_card()`, `_recovery_gap_card()`, … and reduce `generate()` to a list of generator callables plus the ranking; that also makes each card individually unit-testable.
- **Verifier's note:** Substance fully verified, but I'd downgrade severity from high to medium.

The structural facts are all true and reachable in current code. What is overstated is the impact wording "a mistake in one card's dict silently reorders or drops others." The ranking loop at :303-308 does `c["impact_high"] or 0` and `CONF_W[c["confidence"]] / EFFORT_W[c["effort"]]` — a missing or misspelled key in a new inline card raises KeyError and fails loudly, it does not silently drop the card. The sort at :310 also uses `c.get("risk_gmv", 0)`, so alerts without that key are safe. The genuinely silent failure mode is narrower: a wrong *value* (e.g. `card_type` typo'd to "alert", or impact expressed in the wrong unit) misranks the whole list without any error. Real, but a smaller blast radius than "drops others" implies.

There is no correctness bug, no user-facing failure, and nothing on a security or money-correctness path — this is maintainability plus a doc/code mismatch that will mislead one new engineer once. That is medium, not high. The cheap fix matching the doc is to lift the 5 inline dicts into `_paid_unverified_card`, `_recovery_gap_card`, `_high_value_friction_card`, `_repeat_gap_card`, `_concentration_card`, leaving `generate` as a call list plus the ranking block; that alone drops C901 well under the threshold and makes CONTRIBUTING.md:47 true.

### ZB-013 · Copilot formats a transaction count as rial

**Lens:** `data-correctness` · **Severity:** HIGH · **Effort:** small · **Verification:** CONFIRMED

- **Where:** zarin/copilot.py:120 (GET /api/copilot, intent=priorities)
- **Observed:** Live: GET /api/copilot?m=M156&q=این هفته روی چه تمرکز کنم؟ returns «... برآورد تلاش‌های قابل نجات با مسیردهی به درگاه بهتر (تعداد تراکنش): ۱۷۸ ریال تا ۳۵۶ ریال». The psp_friction card carries impact_is_count=true (insights.py:353) and impact_low/high are attempt counts (178/356), but copilot.py:120 unconditionally applies `_rial()`. frontend/src/components/InsightCard.tsx:17 handles impact_is_count correctly, so the same card is right on the dashboard and wrong in the AI answer.
- **Impact:** The copilot states a payment-volume figure in currency, placing a 356-transaction opportunity next to a 196-billion-rial one in the same sentence. On a payments product this is a materially misleading number in the single most quotable surface.
- **Recommended fix:** Mirror the frontend: in copilot.py:119-121 branch on `c.get('impact_is_count')` and render `fa_num(v) + ' تراکنش'`. Better, move the impact→string formatting into one shared helper used by _plan(), so a new card kind cannot regress it again.
- **Verifier's note:** Substance is real and reachable on the default merchant/date range with no special setup; the reproduction, the numbers (178/356) and the cross-surface inconsistency in the claim are all accurate. Severity high is somewhat overstated — I'd assign **medium**. It is display-only: the computation, the card payload and the dashboard are all correct, and the label immediately preceding the number literally reads «(تعداد تراکنش)» ("transaction count"), so the sentence self-contradicts rather than silently asserting a false currency figure. Fix is one line at copilot.py:120 (mirror the InsightCard rule). Two things do push it above low: it is the single most quotable surface, and psp_friction is currently the only impact_is_count card — any future count-based card inherits the same bug, since the formatting is unconditional rather than card-driven. Note the sibling zarin\ops_copilot.py has no priorities/cards branch, so it is not affected.

### ZB-014 · Evidence drawer states an opportunity formula the code does not compute

**Lens:** `data-correctness` · **Severity:** HIGH · **Effort:** small · **Verification:** CONFIRMED

- **Where:** zarin/registry.py:74-76 (Metric "opportunity"), rendered by frontend/src/components/EvidenceDrawer.tsx:83-84,110
- **Observed:** Live evidence for M156's inbank_gap card returns formula = `excess_rate × sessions × conv(own) × median_ticket(own)` and caveat «بازه از خط پایه میانه (کف) و چارک برتر (سقف) همتایان ساخته می‌شود». The actual computation (insights.py:79-82) is `gap × sessions × [0.5|0.75|1.0] × median_ticket_of_lost_outcome` — there is no conv(own) factor, and insights.py:57-58 explicitly states the p25↔p50 band was abandoned as "spuriously narrow". The drawer therefore shows the registry formula, the stale caveat, and the correct method SQL side by side — three contradictory descriptions of one number. docs/ANALYTICS.md:59-71 matches the code; registry.py, which ANALYTICS.md:3 calls «تنها منبع حقیقت», is the wrong one.
- **Impact:** The flagship trust artifact («این عدد از کجا آمد؟») misstates how the headline rial figure was derived. A reader who recomputes from the stated formula gets a different (roughly conv-times-smaller) number and concludes the engine is wrong.
- **Recommended fix:** Update Metric("opportunity") formula_fa to `(your_rate − peer_median) × sessions × recovery_fraction[0.5…1.0] × median_ticket(lost outcome)` and replace the p25/p75 caveat with the scenario-range wording already used in impact_label_fa. Add a test asserting the registry formula string and the _gap_card method SQL reference the same factor set.
- **Verifier's note:** Substance is fully real and reachable in the live product — verified end to end (registry string -> API payload -> drawer render), not just by reading. I would assign medium-high rather than high. Reasons for the downgrade: the computed rial figure is correct (the cap, the recovery band, the loss-outcome ticket all behave as documented in ANALYTICS.md); only its self-description is wrong, and the fix is two strings in registry.py:74-76. Reasons it is not merely low/cosmetic: the wrong text sits on the headline number of the flagship trust surface («این عدد از کجا آمد؟»), a reader recomputing from the stated formula lands ~conv-times low (roughly half), and registry.py is what ANALYTICS.md:3 calls the single source of truth — so the one file designated as authoritative is the one that is wrong. Suggested fix: set formula to `(your_rate − peer_median) × sessions × recovery_fraction[0.5…1.0] × median_ticket(lost outcome)` and replace the p25/p50-band caveat with the recovery-fraction scenario wording already in insights.py:57-58.

### ZB-015 · Insight ranking sorts transaction counts against rial in the same score

**Lens:** `data-correctness` · **Severity:** HIGH · **Effort:** small · **Verification:** CONFIRMED

- **Where:** zarin/insights.py:306-314 (score = impact_high × conf ÷ effort); sort key at :310-314
- **Observed:** Live GET /api/insights?m=M156: inbank_gap score=45,835,891,420 (rial), paid_unverified score=61,847,264,950 (rial), psp_friction score=214 (a transaction count). All three are opportunities sorted by the same numeric key. The PSP card's 356 recoverable attempts at M156's ~41M IRR median ticket is ≈14.6B IRR of real value, yet it is ranked below every rial card by eight orders of magnitude. docs/ANALYTICS.md:79-81 acknowledges the PSP card is denominated in transactions and :84 defines the score as impact_high×conf÷effort, but never reconciles the two.
- **Impact:** A PSP-routing card — the only card naming a concrete, easy, operator-actionable lever — can never reach the top of the ranked action list for any merchant, regardless of its true value. The product's central promise is a correctly ranked action list.
- **Recommended fix:** Normalize to one unit before scoring: give count-denominated cards an `impact_value_irr = impact_high × median_ticket` and score on that, or carry an explicit `score_basis_irr` field per card. Leave the display in transactions.
- **Verifier's note:** Severity high is defensible; I'd keep it high, at minimum medium-high. Substance is exactly as described: a count and a rial figure share one sort key, so the PSP card cannot rank first for any merchant in the dataset (0 of 29), and for 3 merchants it is dropped from the UI entirely by the top-4 slice. Two things temper it slightly — the card's own displayed numbers and label are correct (the frontend does honour impact_is_count for rendering), and it still appears in the list for 26 of 29 affected merchants — but the defect lands squarely on the product's stated central promise (a correctly ranked action list) and hits the only card naming an easy operator-actionable lever. Fix is one line: convert `lost` to rial with the merchant's median ticket before scoring (keep the count for display), or normalise score by unit at insights.py:306.

### ZB-016 · PSP friction card compares non-comparable traffic: the "weak" gateway is the retry rail

**Lens:** `statistics` · **Severity:** HIGH · **Effort:** medium · **Verification:** CONFIRMED

- **Where:** zarin/insights.py:318-366 (_psp_card); live /api/insights?m=M250
- **Observed:** For M250 the card names PSP-08 (5.5% success, 38,394 attempts) vs PSP-01 (61.4%) and estimates 5,366–10,732 recoverable transactions. Probing `attempts` directly: PSP-08 has avg(try_seq)=6.05 while PSP-03/PSP-01 have 1.03/1.38 — PSP-08 is the fallback/retry rail, so its success rate is dominated by attempt-order composition, not gateway quality. No stratification by try_seq, amount, time or BIN anywhere in the query. The deliberate degenerate-rail guard (`ok_rate >= 0.05`, insights.py:329) misses PSP-08 by 0.5pp. The diagnosis then asserts «الگوی ضعف پایدار است» (the weakness pattern is persistent) — a persistence claim never tested.
- **Impact:** A merchant is told to ask ZarinPal to move traffic off a gateway whose apparent weakness is an artifact of it receiving already-failed retries; rerouting would move ~10k retry attempts to another rail and recover far fewer than claimed. This is the exact selection-bias failure the code elsewhere claims to design against.
- **Recommended fix:** Restrict the comparison to first attempts (`try_seq = 1`) or stratify by try_seq and compare within-stratum; require the gap to hold in ≥2 of 3 amount terciles before emitting; drop the unsupported «الگوی ضعف پایدار است» sentence or replace it with a month-over-month stability check.
- **Verifier's note:** Substance real and reachable in current live output, but severity is overstated — I'd assign MEDIUM, not high, and the reviewer's causal story is only half right.

Where the claim holds: no stratification anywhere in _psp_card; the rails compared are genuinely non-comparable (avg try_seq 6.05 vs 1.03/1.38); the degenerate-rail guard misses by 0.47pp; the persistence sentence is a hardcoded assertion; and the evidence block is mislabelled as a first-attempt metric.

Where the claimed impact does not hold. I direct-standardized PSP-08's attempts by try_seq bucket against PSP-01's within-bucket rates: expected extra successes = 10,185, versus the card's crude 10,732 (a ~5% difference; halved by the same 0.5 factor it becomes 5,093 vs impact_high 10,732 / impact_low 5,366). Stratifying by attempt order barely moves the number because PSP-08 is worse in *every* stratum — at try_seq=1 it is 0.2715 vs PSP-01's 0.6367 on 5,835 first attempts. So "its success rate is dominated by attempt-order composition, not gateway quality" is not supported; composition explains only part of the gap.

The real inflation is elsewhere, and it is a different bug: 14,493 of the 36,394 failed PSP-08 attempts sit in sessions that converted anyway, and 8,421 of the 19,267 sessions touching PSP-08 already succeeded on another PSP. The card counts attempts as "recoverable transactions" (impact_is_count=True), so roughly 40% of the count is already-won sessions — attempt-level counting, not selection bias, is what inflates it.

Also: PSP-08 exists only from April onward and its monthly rate is 0.2132 (Apr) → 0.0012 (May) → 0.0002 (Jun). It is a rail that died in May, not a "weak" one; the 6-month average of 0.0547 is an April artifact that carries it over the 0.05 guard. Consequences: (a) the guard's own stated intent — exclude broken/off gateways — is defeated by period-averaging, which is the sharper fix than adding stratification; (b) the recommended action (route traffic away from PSP-08) is in fact correct for this merchant, so the merchant is not harmed, which is the main reason this is medium rather than high; (c) the "پرتکرارترین کدهای خطا" clause is built from 4 rows total (only 4 PSP-08 failures carry a switch_response_code), so it presents n=4 as the most frequent error codes.

### ZB-017 · Evidence drawer publishes a formula and caveat that contradict the estimator that produced the number

**Lens:** `statistics` · **Severity:** HIGH · **Effort:** small · **Verification:** CONFIRMED

- **Where:** zarin/registry.py:74-76 (Metric "opportunity"); rendered at frontend/src/components/EvidenceDrawer.tsx:84,110
- **Observed:** Live drawer payload for M215 contains formula `excess_rate × sessions × conv(own) × median_ticket(own)` and caveat «بازه از خط پایه میانه (کف) و چارک برتر (سقف) همتایان ساخته می‌شود», while the same payload's method string (insights.py:125-128) reads `(your_rate − peer_median) × sessions × recovery_fraction[0.5…0.75…1.0] × median_ticket_of_lost_sessions`. The `conv(own)` factor no longer exists in the code, and insights.py:58 explicitly says the p25↔p50 band was abandoned as «spuriously narrow» — the registry still advertises it.
- **Impact:** The evidence drawer is the product's entire auditability claim («این عدد از کجا آمد؟») and it presents two mutually contradictory derivations in one panel. Anyone reconciling the figure against the stated formula cannot reproduce it; the stale text has already propagated into the product's own external description of the estimator.
- **Recommended fix:** Update Metric("opportunity") formula_fa to the recovery-fraction form and replace the p25/p50 caveat with the scenario-band caveat; add a test asserting the registry formula string and the method string emitted by _gap_card name the same factors.
- **Verifier's note:** Substance is real and reachable on the default M215 view; registry.py:74-76 formula, definition_fa and caveat all describe an estimator the code no longer implements, and the same stale wording propagated to docs/DECISIONS.md:47 ("شکاف نرخ × جلسه‌ها × تبدیلِ خود × تیکتِ خود، کف=p50 و سقف=چارک برتر همتایان"). Severity overstated: I'd assign MEDIUM, not high — no computed number is wrong, no data or money path is affected; it is stale user-facing copy in the auditability panel. Fix is three strings in zarin/registry.py:74-76 plus one line in docs/DECISIONS.md:47.

### ZB-018 · "First half vs second half" compares unequal windows, with no minimum-window guard on the copilot path

**Lens:** `statistics` · **Severity:** HIGH · **Effort:** small · **Verification:** CONFIRMED

- **Where:** zarin/insights.py:375-381 (_change_alert), zarin/copilot.py:43-47, frontend/src/pages/ChangesPage.tsx:22-32,86
- **Observed:** mid = d1 + (d2−d1)/2 with date arithmetic truncating: a 31-day selection yields before=16 days, after=15 (verified for 2026-01-01..2026-01-31 and 2026-01-15..2026-02-14); 2026-02-01..2026-03-31 yields 30 vs 29. Raw session counts sit side by side under «نیمه اول»/«نیمه دوم» with no day count and no per-day normalization, so the LMDI `sessions` factor absorbs the ~6% calendar difference. copilot.py applies the same split with no length floor: live /api/copilot?m=M156&f=2026-03-01&t=2026-03-05 returns a 3-day vs 2-day decomposition described as «بین نیمه اول و دوم این بازه» with confidence "high". insights._change_alert has a ≥27-day guard; the copilot path has none.
- **Impact:** On any odd-length window the reported driver mix is biased toward "sessions"; on short windows the copilot confidently attributes a −102M rial "sessions" contribution that is largely a one-extra-day artifact. No day-of-week normalization either, so even a 15/15 split mixes different weekend compositions.
- **Recommended fix:** Use floor-to-even windows (drop the odd middle day) or normalize the sessions factor per day; apply the ≥27-day guard in copilot._plan and downgrade confidence below it; show each half's day count in the ChangesPage table header.
- **Verifier's note:** Substance confirmed; I'd downgrade severity from high to MEDIUM.

What holds:
- Unequal halves on any odd-length span (verified above), backend and frontend agree on the same biased split (frontend/src/pages/ChangesPage.tsx:27-29 `Math.floor(spanDays / 2)` -> same 16/15).
- No per-day normalization anywhere: zarin/analytics.py:247-262 passes raw `period_agg` totals to LMDI, so the day-count difference lands entirely in the `sessions` factor.
- No minimum-window guard on the copilot path while insights has one — asymmetry confirmed, and the copilot still labels the result confidence "high".
- No day-of-week normalization either (confirmed by reading analytics.changes — nothing weekday-aware).

What is overstated:
1. Reachability of the dramatic case. The shipped UI only offers three presets (frontend/src/ctx.tsx:43-61): d30 -> 30 days -> 15 vs 15 (equal), d90 -> 90 days -> 45 vs 45 (equal), and the default "کل دوره" -> 2026-01-01..2026-06-30 -> 91 vs 90 days. So the in-product worst case is a ~1.1% day-count bias, not ~6%. The -102M / 3-vs-2-day case requires hand-crafted f/t on the public API — real (no auth on /api/copilot) but not a click-path in the product.
2. "no day count" on ChangesPage is not accurate: line 55 renders the actual date ranges of both halves (`{faDate(d.before.from)} تا {faDate(d.before.to)} ← ...`), so the 16-vs-15 asymmetry is visible, just not normalized or called out. The raw-counts-side-by-side and missing normalization parts of the claim stand.

Cheapest real fix (one place, all callers): floor the split in analytics.changes / add a shared helper — clamp both halves to equal day counts (drop the odd middle day) and reject windows under N days there, rather than patching copilot.py and insights.py separately.

### ZB-019 · Operator-token gate on /api/admin/* is fail-open by default

**Lens:** `security` · **Severity:** HIGH · **Effort:** small · **Verification:** CONFIRMED

- **Where:** zarin/api.py:34-37 (`_admin_guard`), zarin/config.py:20 (`ADMIN_TOKEN = os.environ.get(..., "")`)
- **Observed:** `if ADMIN_TOKEN and not hmac.compare_digest(...)` — when the env var is unset the guard is a no-op. Verified live: `curl -o /dev/null -w '%{http_code}' http://localhost:8630/api/admin/platform` → 200 with no header. tests/test_control.py:83 codifies this as intended (`test_admin_open_on_loopback_by_default`). Dockerfile:9 sets `ZARIN_HOST=0.0.0.0`, so the open posture and a non-loopback bind ship in the same image (compose mitigates by publishing to 127.0.0.1 only).
- **Impact:** Platform-wide GMV, concentration, per-endpoint telemetry and AI cost are exposed to any network peer whenever the operator forgets one env var. A security control whose default is "off" is the one that is off in the incident.
- **Recommended fix:** Invert the default: require ZARIN_ADMIN_TOKEN and refuse to start (or serve 503 on /api/admin/*) when it is unset and HOST is not loopback. Keep the loopback-open path as an explicit opt-in flag rather than the absence of config.
- **Verifier's note:** Substance fully verified, every supporting detail too: tests/test_control.py:83 `test_admin_open_on_loopback_by_default` asserts 200 with no token; Dockerfile:10 sets `ZARIN_HOST=0.0.0.0`; docker-compose.yml publishes `127.0.0.1:8630:8630` with the comment "the app has no auth (evaluator mode)". Severity, however, is overstated at high — I would assign MEDIUM. Reaching exposure requires the operator to deviate from the shipped compose (which binds loopback) AND skip the token documented as mandatory in docs/DEPLOYMENT_SPEC.md:85; the default `HOST = "127.0.0.1"` (config.py:13) is a second layer. `ZARIN_HOST=0.0.0.0` in a container is required for any published port to reach the app at all, so it is not independently incriminating — the claim itself concedes compose mitigates. Exposed data is anonymized aggregate demo analytics with a deliberately scaled `adjusted_fee` column (no PII, no per-customer identifiers), and the only state mutation is a feedback counter (POST /api/admin/copilot/feedback) plus a `@lru_cache(maxsize=1)`-capped ai-eval. The fail-open default is still a genuine defect worth fixing — the guard should require the token whenever HOST is non-loopback — but it is not a high.

### ZB-020 · Grounding guard checks only multi-digit numbers — arbitrary model text passes as "grounded"

**Lens:** `security` · **Severity:** HIGH · **Effort:** medium · **Verification:** CONFIRMED

- **Where:** zarin/ai/gateway.py:37-60 (`_digit_runs` / `is_grounded`), rendered at frontend/src/components/Copilot.tsx:113
- **Observed:** `_digit_runs` keeps only runs with ≥2 significant digits, and `is_grounded` returns True when the LLM output contains none. Probe: `is_grounded('حساب شما مسدود شده است. برای رفع مشکل به https://evil.example/zarinpal مراجعه و رمز کارت خود را وارد کنید.', det)` → True; `is_grounded('نرخ تبدیل شما ۹ برابر بدتر شده', det)` → True. That text becomes `answer_fa` and is shown with note_fa "این پاسخ بر پایه اعداد قطعیِ موتور تحلیلی است". The user's raw question is interpolated into the prompt at gateway.py:87 with no injection filter, and zarin/ai/eval/cases.py has no prompt-injection case (refusal cases cover thin data, false causality, out-of-scope, malformed).
- **Impact:** A prompt-injected or simply misbehaving free third-party model can present unsupported causal claims, single-digit magnitude claims, or a bank-phishing URL to a merchant under the product's own grounding assurance. React escaping prevents XSS, but not the phishing/misinformation payload.
- **Recommended fix:** Extend the guard beyond digits: reject LLM output containing URLs, emails, phone numbers or markdown links; check 1-digit runs too; and add an injection case to zarin/ai/eval/cases.py ("دستورات قبلی را نادیده بگیر و ...") asserting the deterministic fallback is returned.
- **Verifier's note:** Substance is real and reachable; I'd assign medium-high rather than high for the repo as it stands, and high once the feature is switched on.

Two calibrations on the claim:

1. Gated on config, not on by default. `OPENROUTER_API_KEY` is unset here (`uv run python -c "from zarin.config import OPENROUTER_API_KEY; print(bool(OPENROUTER_API_KEY))"` -> False), so `default_provider()` returns None and gateway.py:76 takes the deterministic-only path. The bug is dormant until a key is configured — but that is the intended production config for the product's headline AI feature, and the configured model is a free third-party one (`deepseek/deepseek-chat-v3-0324:free`), so it is a real deployment state, not a hypothetical.

2. One factual slip in the finding: `note_fa` is returned in the API contract but is NOT rendered by Copilot.tsx. Grep shows the only `note_fa` reference in that file is line 64 (an error stub); the UI instead shows a `با کمک هوش مصنوعی` chip. The grounding assurance is therefore weaker in the UI than the finding implies — but the answer is still framed as product AI output, so the misinformation/phishing impact stands.

Correctly scoped in the finding: React escaping does prevent XSS, and `safe_context._BANNED_KEY_SUBSTRINGS` does prevent data exfiltration — this is purely a content-trust issue.

Cheapest fix consistent with the module's own stated contract: reject `comp.text` containing a URL/scheme (`re.search(r"https?://|www\.", comp.text)`) unless it traces to the deterministic text, in the same `is_grounded` guard all callers already route through. Adding one injection case to eval/cases.py would cover the regression.

### ZB-021 · Unhandled 500s are invisible to the Control Center's own error metric

**Lens:** `reliability` · **Severity:** HIGH · **Effort:** small · **Verification:** CONFIRMED

- **Where:** zarin/obs.py:23-29 (middleware) → /api/admin/performance, Ops «کارایی» page
- **Observed:** `resp = await call_next(request)` has no try/except/finally, and the middleware sits outside Starlette's ServerErrorMiddleware, so an exception propagates past `record()`. Probe: monkeypatched analytics.overview to raise, GET /api/overview?m=M156 → HTTP 500, and obs.summary() returned {'total': 0, 'has_data': False} — the request was never recorded. HTTPException 4xx (404/400/422) ARE recorded, so only server errors are lost.
- **Impact:** `error_rate` in obs.py:77 is len(status>=500)/total over a set that cannot contain 500s — it is pinned at 0 by construction. The Performance page's prominent «نرخ خطای سرور» tile (OpsPerformance.tsx:40-41) and the `attention` block (obs.py:68) that keys off error_rate>0 can never fire, and the ops copilot answered live with «نرخ خطا ۰٫۰٪». During an outage the operator surface shows a green, plausible, wrong screen.
- **Recommended fix:** Wrap call_next in try/except: record(status=500, latency) and re-raise. Add a test asserting a raising endpoint produces an obs event with status 500 (the existing test_admin_performance_records_requests only covers success).
- **Verifier's note:** Severity high is correct, keep it. The blast radius is the operator's primary incident-detection surface: `error_rate`, the per-endpoint `error_rate` column, the red-tile threshold, and the whole `attention` high-severity branch are all structurally pinned at zero, and the ops copilot reads the same dict — so it confidently answers «نرخ خطای ۰٫۰٪» mid-outage. Worse than a metric that is merely missing: it is a plausible-looking green that actively argues nothing is wrong, and finding #2 shows the failure is not hypothetical (the codebase's own db.py comment names 500s as a live production mode). Not data loss or a security issue, which is the only reason it is not critical.

Two small corrections to the finding's wording, neither affecting the verdict: the frontend path is `frontend/src/ops/OpsPerformance.tsx`, not `src/pages/`; and the reported line range obs.py:23-29 should be read as the whole middleware, with the specific defect at line 25.

Fix is a three-line try/finally around `call_next` recording status 500 on exception — worth noting because the cost/benefit is lopsided, e.g.:

    t0 = time.perf_counter()
    status = 500
    try:
        resp = await call_next(request)
        status = resp.status_code
        return resp
    finally:
        if <same path filter>:
            record(request.method, path, status, (time.perf_counter() - t0) * 1000)

Compute `path` before the try. A regression test is cheap: the monkeypatch probe I ran (force analytics.overview to raise, GET /api/overview?m=M156, assert obs.summary()["total"] == 1 and error_rate == 1.0) fails today and passes after the fix.

### ZB-022 · Bootstrap /api/meta failure leaves the merchant workspace in a permanent skeleton

**Lens:** `reliability` · **Severity:** HIGH · **Effort:** small · **Verification:** CONFIRMED

- **Where:** frontend/src/ctx.tsx:35-41
- **Observed:** `get<Meta>("meta", {}).then(...)` has no `.catch`. On failure: unhandled promise rejection, `meta` stays null, `merchant` stays "", and useData's effect returns early at ctx.tsx:105 leaving state {loading:true} forever. Overview.tsx:25 then renders <Loading/> indefinitely; CopilotPage renders the chat hero with `glance` undefined (CopilotPage.tsx:29) and no error. Login (Login.tsx) is independent of meta, so the user authenticates successfully into the broken workspace. Period also silently falls back to hardcoded 2026-01-01..2026-06-30 (ctx.tsx:50-51). This is the *likely* failure: pipeline.ensure_built (zarin/pipeline.py:213-218) only checks file existence, so a stale-schema mart set starts cleanly and then 500s on the db.py:36 guard at first query.
- **Impact:** The single most probable production failure (backend down, stale marts, 500 on meta) yields an eternally-loading dashboard with no error, no retry, and no hint — while db.py:37 has already composed the exact fix instruction («Rebuild them: uv run python -m zarin.pipeline») that nothing ever displays.
- **Recommended fix:** Add `.catch` on the meta fetch, surface a retryable error banner in Shell when meta is null-with-error, and have ensure_built() call db.connect() so a stale-schema mart fails loudly at startup instead of on every request.
- **Verifier's note:** Substance is fully real and reachable; I'd rate it medium-high rather than high. It is availability/observability only — no data loss, no security exposure — and it needs a backend failure to trigger. What earns the high end of that range is that it is silent and terminal: the most probable production failure (stale marts after a schema-changing pipeline change, which `ensure_built` is specifically unable to detect) produces a dashboard that looks like it is still loading, forever, with the exact remediation string already composed one layer down and thrown away.

Two small corrections to the claimed evidence, neither of which changes the verdict:

1. The period fallback to hardcoded `2026-01-01..2026-06-30` (ctx.tsx:50-51) is inert in the *merchant* workspace during this failure — with `merchant === ""` no request is ever issued, so the wrong window is never used. It does bite the *ops* workspace: `useAdmin` (ctx.tsx:78-95) does not gate on `merchant`, so ops pages fetch and render successfully against a silently wrong hardcoded date range. That is arguably the more insidious half — wrong numbers with no marker beats no numbers.

2. FastAPI's `@lru_cache(maxsize=1)` on `meta()` (api.py:60-62) does not cache the failure (exceptions aren't cached), so a manual browser reload after the backend is fixed does recover. There is just no in-app path to it.

The fix is a `.catch` on ctx.tsx:36 that sets a meta-error state plus one render branch for it — and, separately, worth propagating the db.py guard message into the 500 body so the operator sees the rebuild instruction that was written for them.

### ZB-023 · Marts are unclustered — every merchant query full-scans all 2.06M sessions

**Lens:** `scalability` · **Severity:** HIGH · **Effort:** small · **Verification:** CONFIRMED

- **Where:** zarin/pipeline.py:207 (`COPY {name} TO ... (FORMAT PARQUET)` with no ORDER BY)
- **Observed:** `parquet_metadata('data/marts/sessions.parquet')` shows all 17 row groups have merchant_key min/max of M1..M99 — zero zone-map pruning is possible. Measured floor: the same median+distinct-card query costs 6.2 ms for M70 (**1 session**), 25.8 ms for M156 (55,940), 49.7 ms for M250 (1,055,912). ~6 ms of every session-grain query is pure scan of other merchants' rows.
- **Impact:** Per-merchant request cost is O(total platform rows), not O(that merchant's rows). At 100x merchants (~206 M sessions) that fixed floor becomes ~600 ms per session query; `/api/insights` makes ~10 of them, so the landing page goes from 277 ms to multiple seconds purely from data the merchant will never see.
- **Recommended fix:** `COPY (SELECT * FROM sessions ORDER BY merchant_key, d) TO …` so row-group min/max prunes, or emit Hive-partitioned output (`PARTITION_BY (merchant_key)`) and register it with `read_parquet(..., hive_partitioning=true)`. One line in the pipeline; no query changes.
- **Verifier's note:** Substance is real, severity is overstated — I'd assign LOW (at most low-medium), not high.

What holds: the marts are genuinely unclustered, pruning is genuinely zero, and `ORDER BY merchant_key` on line 207 is a one-clause fix that measurably helps. Writing a sorted copy and re-timing the identical queries: M156 20.2 ms -> 9.7 ms (2.1x), and the file shrinks 66.2 MB -> 59.9 MB from better run-length/dictionary locality. Worth doing.

What does not hold — the claimed mechanism and the extrapolation:

1. "~6 ms of every session-grain query is pure scan of other merchants' rows." Wrong. On the sorted copy, where only 1 of 17 row groups matches M70, the same M70 query still costs 4.87 ms vs 5.75 ms unsorted — clustering recovers only ~0.9 ms (15%) of the floor. A parquet containing M70's single row alone runs the same query in 1.91 ms, so ~3 ms of the floor is fixed per-file open/footer/statistics cost (28 columns x 17 row groups of stats) that ORDER BY cannot touch. EXPLAIN ANALYZE already reports 0 rows out of READ_PARQUET in both cases — filter pushdown is working; the rows are not being materialized.

2. "At 100x merchants the fixed floor becomes ~600 ms." Wrong by roughly an order of magnitude. I built a 5x replica (10,314,195 rows) and re-timed the M70 query: 10.64 ms unsorted, 8.49 ms sorted. 5x the data produced 1.85x the latency, not 5x — the floor is dominated by fixed and parallel-scan costs, so a 100x linear extrapolation to 600 ms is unsupported, and sorting only removes ~20% of it at that scale.

3. The merchant distribution undercuts the impact case: 343 merchants, median 69 sessions, p90 2,677. The median merchant sits squarely in the floor-dominated regime where clustering buys ~0.9 ms per query. Across the ~7 `FROM sessions` queries in zarin\insights.py that is ~6 ms off a 277 ms page (~2%). Pruning only pays for the handful of large merchants, and the single largest (M250, 51% of all rows) cannot be pruned meaningfully by definition.

Recommendation: keep the finding, fix it (it is one clause and also saves 10% on disk), but re-rate it low and drop the "landing page goes to multiple seconds" impact narrative — it is not what the data shows.

### ZB-024 · /api/insights issues 23–25 sequential uncached queries, several redundant

**Lens:** `scalability` · **Severity:** HIGH · **Effort:** medium · **Verification:** CONFIRMED

- **Where:** zarin/insights.py:135 `generate()` (verified by instrumenting `db.q`/`db.q1`)
- **Observed:** Instrumented run: `insights M156` → 23 queries, `insights M250` → 25 queries, slowest single query 82.7 ms. Redundancy is visible in the code: `_gap_card` runs up to two `quantile_cont(amount,0.5)` full scans over `sessions` (insights.py:72 and 75) and is called twice; the same verified-ticket quantile is computed a third time at insights.py:188; `_change_alert` calls `changes()` which runs two more `period_agg`s over a window already aggregated at insights.py:136.
- **Impact:** The most expensive merchant endpoint is also the second fetch on the chat-first landing page, and it has no cache at all — every tab switch back to Overview re-runs all 25 queries (the frontend `useData` hook in ctx.tsx:98 keeps no cache either). Under the global lock this endpoint alone caps the app at <3 req/s.
- **Recommended fix:** Hoist the per-outcome median tickets into one `SELECT outcome, quantile_cont(amount,0.5) … GROUP BY outcome` call and pass the dict into `_gap_card`; pass the already-computed `period_agg` into `_change_alert` instead of re-deriving it; then add a small TTL/LRU cache keyed on (m, f, t) since the marts are immutable between pipeline builds.
- **Verifier's note:** Substance is real, headline numbers and the redundancy specifics are wrong. I'd assign MEDIUM, not high.

Real and reachable: `/api/insights` is uncached at both ends, issues ~17 sequential lock-serialized queries, costs ~0.5s wall on the live server, and caps the app around 3.4 req/s. Fix is one line of `lru_cache` on `generate` (or on the route), which is why the severity matters less than usual.

Corrections to the finding as written:

1. Query count is inflated ~50%. Actual DB executions are 16 (M156) and 17 (M250) including `api._dates`' `min(d)/max(d)` probe; add `_check_merchant` and the endpoint totals 17/18 — not 23/25. The claimed numbers are exactly what you get by instrumenting `db.q` AND `db.q1` and summing: `q1` (db.py:69-71) is a thin wrapper that calls `q`, so every `q1` is counted twice. M156: 15 executes + 8 `q1` = 23. M250: 16 + 9 = 25. The stated instrumentation method produced the stated numbers by double-counting.

2. The claimed redundancies mostly do not fire. The two `quantile_cont` calls at insights.py:72 and :75 are an `or`-fallback — line 75 only runs when line 72 returns NULL/0, and it ran zero times for either merchant. The two `_gap_card` invocations pass different `$o` (`no_attempt` vs `abandoned_inbank`), so they are different queries, not a repeated one. Line 188's quantile sits inside the `recovery_gap` branch behind `gap > 0.03` and did not fire in either run. The three `period_agg` calls cover three *different* windows (full period, first half, second half via `_change_alert` -> `changes()`), so they are distinct work — combinable into one grouped query, but not redundant as claimed.

3. Slowest query is real but misattributed to the quantiles: it is the `ntile(5) OVER (ORDER BY amount)` full-window sort at insights.py:208-215 (78.2ms) and the per-card concentration CTE at :268-273 (56.3ms). Those two are 51% of the DB time and are where a rewrite would actually pay.

### ZB-025 · Full 1.95M-row attempts aggregate on every /api/quality and /api/admin/platform, uncached

**Lens:** `scalability` · **Severity:** HIGH · **Effort:** small · **Verification:** CONFIRMED

- **Where:** zarin/api.py:243-246 (`/api/quality` anomalies) and zarin/control.py:63-67 (`admin_platform` anomalies)
- **Observed:** Both run `session_key IN (SELECT session_key FROM attempts GROUP BY 1 HAVING sum(ok::int)=0)`. Timed in isolation: 108.3 ms — a full group-by over all 1,949,353 attempt rows. `/api/quality` carries no `_admin_guard` and no `lru_cache`; measured end-to-end ~126 ms server-side, and `/api/admin/platform` ~232 ms across its 9 queries.
- **Impact:** These are data-version-invariant facts (the code even hardcodes the answer in Persian prose at api.py:256: "۲۸ جلسه Verified بدون تلاش Verified"), yet they are recomputed from scratch on every hit of an unauthenticated endpoint. Cost scales linearly with total attempts, so it degrades 100x at 100x scale while returning a constant.
- **Recommended fix:** Compute `verified_wo_ok_try` / `reversed_sessions` once in `pipeline.build()` and store them (a tiny `data_quality` mart or a JSON sidecar); at minimum wrap `/api/quality` in `@lru_cache(maxsize=1)` as `/api/meta` already is.
- **Verifier's note:** Substance real and reachable; I'd assign MEDIUM rather than high, with one correction and one aggravator the finding missed.

Correction to the claimed evidence: the finding says the code "hardcodes the answer" at api.py:256 as "۲۸ جلسه Verified بدون تلاش Verified". The query actually returns verified_wo_ok_try = 1, not 28. So that Persian prose line is stale/wrong — a separate correctness bug worth its own finding — and it does not stand as proof that the value is a known constant. The invariance argument holds anyway on stronger grounds: the marts are read-only parquet registered as DuckDB views at db.py:29-31, so nothing can change the answer within a process lifetime.

Aggravator the finding missed, and the reason it isn't merely cosmetic: `q()` serializes every query in the process behind a single module-global RLock (db.py:14, `with _lock:` at :63). A ~110 ms unauthenticated scan therefore blocks *all* other endpoints, capping the whole app near ~8 req/s from one client hammering /api/quality. That is the real risk here, not the 122 ms itself.

Why medium not high: absolute latency is ~0.12 s / ~0.30 s on a single-tenant hackathon build over static local parquet, and there is no correctness or data impact. Raise to high if this is ever exposed publicly, given the unauthenticated + global-lock combination.

Fix is one line and the pattern already exists in this file — api.py:195-196 wraps `_cached_eval()` in `@lru_cache(maxsize=1)`. Same treatment on the anomalies lookup; `control.platform` needs the cache keyed on (f, t).

### ZB-026 · Control Center recommends merchant-level action but offers no merchant drilldown or search

**Lens:** `product` · **Severity:** HIGH · **Effort:** medium · **Verification:** CONFIRMED

- **Where:** zarin/control.py:80-98 (_platform_insights) + frontend/src/ops/* (all five pages)
- **Observed:** The platform insight reads "پذیرندگان دارای بیشترین مبلغ تاییدنشده را ... در اولویت بگذارید" (control.py:86) and OpsOverview renders it verbatim. Live /api/admin/platform returns only KPIs, top-10 categories, a top-5 concentration ratio, and anomaly counts — no merchant rows. Grep across frontend/src/ops/ finds no merchant table, no merchant search, no merchant deep-link; the merchant selector is merchant-workspace-only (App.tsx:119).
- **Impact:** The internal team's first two questions — "which merchants are in trouble right now?" and "look up merchant X" — cannot be answered in the product. The one concrete action the Control Center recommends is unexecutable inside it, so an ops user must leave for SQL. This is the single largest reason the ops surface reads as a monitoring poster rather than a working tool.
- **Recommended fix:** Add a merchant table to OpsOverview ranked by the same signals the insights fire on (unverified amount, no-attempt rate, GMV delta), each row deep-linking into that merchant's workspace view. The queries already exist in analytics.py/insights.py at merchant grain.
- **Verifier's note:** Severity high is appropriate as assigned — keep it. Qualifier: this is a product-scope gap, not a correctness or security defect. Every figure the Control Center displays is accurate and honestly sourced (control.py deliberately returns has_data=False rather than fabricating); what is missing is the drilldown the product's own recommended action presupposes. Two minor precisions on the claim's wording: (a) the merchant selector at App.tsx:120-129 is an unranked 200-item dropdown with no search and no ranking by unverified amount, so even after logging out and re-entering as a merchant, "which merchants have the largest unverified amount" still cannot be answered; (b) the live categories array returned 5 rows on this dataset, not 10 — the LIMIT 10 at control.py:40 is just not saturated. Neither weakens the finding.

### ZB-027 · Ranked action cards are terminal: no navigation, no state, no follow-through

**Lens:** `product` · **Severity:** HIGH · **Effort:** medium · **Verification:** CONFIRMED

- **Where:** frontend/src/components/InsightCard.tsx:24-60; frontend/src/pages/Overview.tsx:76-85
- **Observed:** InsightCard renders only text plus an EvBtn. Card copy routes the user in prose — gmv_change's action says "صفحه «قیف پرداخت» را ببینید" (insights.py:396) and inbank_gap says "جزئیات در صفحه ..." — but there is no link, button, or router call anywhere in the component. There is also no dismiss, snooze, mark-done, assign, or seen-state: /api/insights is a pure recomputation with no persistence (api.py:107-111), and no card-state store exists in zarin/store.py.
- **Impact:** The "action feed" is a read-only list. A merchant cannot act on a card without manually finding the page it named, cannot clear a card they have handled, and cannot tell next week whether the 61.8B rial unverified backlog is the same backlog or a new one. The act → measure → close loop that the whole insight-first thesis rests on is never closed.
- **Recommended fix:** Give each card kind a target page id and render the action as a real CTA; persist per-merchant card state (dismissed / done / snoozed-until) in the existing EventLog store and show "you actioned this N days ago — the number has moved X%" on recurrence.
- **Verifier's note:** Substance is real and fully reachable; severity is overstated. I'd assign MEDIUM, not high.

Why medium: this is a missing-feature / product-thesis gap, not a defect. Nothing in the current code is broken, wrong, or exploitable — the cards render and the evidence drawer works as designed. There is no correctness, data-loss, or security dimension.

Two details in the claim's evidence are inaccurate, though they don't change the verdict:
- The inbank_gap example is wrong. Its action text (insights.py:167) is "مسیر انتقال به درگاه را روی موبایل و دسکتاپ تست کنید؛ خطاهای ریدایرکت و تایم‌اوت سمت خودتان را لاگ و رفع کنید." — a concrete instruction, not "جزئیات در صفحه ...". That string does not exist in insights.py. Of the 10 action_fa strings, only ONE (gmv_change, line 396) routes the user in prose; the other nine are self-contained instructions ("enable auto-verify", "run a win-back SMS campaign", "ask ZarinPal support to shift PSP traffic"). insights.py:392 even carries the comment "# a concrete, factor-tied next step — not just 'open another page'", so the author was deliberately avoiding exactly this pattern. The "cards route the user in prose with no link" framing is true of 1 of 10 cards, not the set.
- The "same backlog next week?" impact is partly theoretical here: the dataset is a fixed historical window (/api/meta returns range 2026-01-01..2026-06-30), not a live feed, so there is no "next week" in the current deployment for seen-state to disambiguate.

The one genuinely actionable piece is cheap: gmv_change's action names "صفحه «قیف پرداخت»" and there is no way to get there. Lifting `go` from App.tsx into ctx.tsx and adding an optional `target_page` field on that one card is a few-line diff. Dismiss/snooze/assign is a real backlog feature but needs a user identity and a mutable store this hackathon-stage app doesn't have (store.py's own docstring: "This is deliberately the *hackathon* store").

### ZB-028 · Flagship card's headline action is wrong for ~100% of the merchants it fires on

**Lens:** `business` · **Severity:** HIGH · **Effort:** small · **Verification:** CONFIRMED

- **Where:** zarin/insights.py:152-153 (paid_unverified diagnosis_fa / action_fa)
- **Observed:** The card blames "callback error or forgetting manual verification" and instructs «تایید خودکار تراکنش‌ها را در فروشگاه فعال کنید». Probing the mart: paid_unverified sessions split 8,705 on verify_type='Automated' vs exactly 1 on 'Manual'. Every affected merchant already has auto-verify on. verify_type is carried into the sessions mart (pipeline.py:71) and never read by the insight engine.
- **Impact:** The #1-ranked card on the product's flagship discovery gives an instruction that is a no-op. A ZarinPal ops reviewer checks this in one query and the whole engine's credibility drops with it; a merchant who follows the advice sees no change and disengages.
- **Recommended fix:** Join verify_type into the card. For Automated merchants the real diagnosis is a callback/verify-API failure — segment by PSP and settled_at date, and say "your verify callback is failing" with the failing rail named. Reserve the auto-verify advice for the Manual segment.
- **Verifier's note:** Substance is real and reachable; I would downgrade severity from high to MEDIUM.

What is genuinely wrong: the lead clause of action_fa (insights.py:153) tells the merchant to switch on auto-verify, and 8,705 of 8,706 affected sessions already have verify_type='Automated'. The "فراموش‌شدن تایید دستی" half of diagnosis_fa (line 152) is likewise wrong for ~100% of the population. The engine has the disambiguating column sitting in the same mart row and ignores it.

Why not high:
- The action string is a three-clause «یا» sentence, not a single instruction. Only the first clause is a no-op — "خطای بازگشت پرداخت را رفع کنید" (fix the callback error) and "این پرداخت‌ها را از پیشخوان زرین‌پال تعیین تکلیف نمایید" (settle these from the ZarinPal dashboard) are both correct and actionable for an Automated merchant. A merchant who follows the card is not left with nothing, contrary to the "sees no change and disengages" framing.
- No number is wrong. impact_low/impact_high are the literal settled amount and the label correctly says "برآورد نیست". The defect is copy/diagnosis, not computation, so it does not propagate into ranking, opportunity math, or evidence SQL.

Why not lower than medium: it is the #1-ranked card on the flagship surface, the misdiagnosis is checkable in one query by exactly the audience being pitched, and the fix is one line — read the already-materialized verify_type and branch the diagnosis/action (callback-failure path vs manual-verify path), which would also correctly serve the 86,316 Manual verified sessions that exist elsewhere in the data.

### ZB-029 · 61.8B IRR presented as claimable money with no claimability or expiry framing

**Lens:** `business` · **Severity:** HIGH · **Effort:** small · **Verification:** CONFIRMED

- **Where:** zarin/insights.py:154-156, impact_label_fa «مبلغ واقعی در انتظار تعیین تکلیف (برآورد نیست)», confidence "high"
- **Observed:** The card asserts a hard rial figure at high confidence, ranked #1, and the overview repeats it as a headline KPI (frontend/src/pages/Overview.tsx:68-74) and as a chat-landing stat («در انتظار تایید شما ۶۱٫۸ میلیارد», docs/screenshots/rd-chat.png). Nothing in insights.py, docs/ANALYTICS.md or docs/DATA_AUDIT.md states whether an unverified settled payment stays claimable or reverses to the payer after a window; no settled_at age is computed. Dataset support is thin on this point: 8,706 Paid sessions but only 1 Reversed in six months.
- **Impact:** This is the single largest overclaim risk in the product. If ZarinPal's real policy reverses unverified transactions, the product has told merchants they are owed money that no longer exists — and the "not an estimate" label removes every hedge. One such incident kills the trust the rest of the evidence system was built to earn.
- **Recommended fix:** Add an age dimension (settled_at → today) and split the figure into "within the verification window — recoverable" and "past window — reconcile with support". State the ZarinPal reversal policy in the evidence caveats. Until the policy is confirmed, soften impact_label_fa from «مبلغ واقعی در انتظار تعیین تکلیف» to «مبلغ تسویه‌شده بدون تایید — وضعیت وصول را با پشتیبانی بررسی کنید».
- **Verifier's note:** Substance confirmed; severity is defensible but slightly generous — I'd assign medium-high rather than high. Two qualifiers the finding's framing skips: (1) the observation sentence itself is factually precise ("N payments totaling X settled at the bank, merchant-side final verification never happened") — the defect lives in the impact_label, the confidence=high/effort=easy pair that makes it outrank everything, and the action text implying panel-recoverability, not in the arithmetic; (2) the dataset gives no evidence of reversal-after-window (Paid looks terminal here: 8,706 Paid vs 1 Reversed over six months), so the "money no longer exists" scenario is a real-policy hypothesis, not something the data shows. What IS unambiguously wrong is that a 4-month-old settled-unverified row is rendered identically to a fresh one, at the top of the ranking, with "برآورد نیست" explicitly stripping the hedge. Fix is one line of framing plus a settled_at age bucket — `settled_at` is already in the sessions table and unused, so it costs nothing to surface.

### ZB-030 · No tenancy: any merchant's full business data is readable by merchant key

**Lens:** `business` · **Severity:** HIGH · **Effort:** medium · **Verification:** CONFIRMED

- **Where:** zarin/api.py — merchant routes (/api/overview, /api/insights, /api/customers …) carry no auth dependency; only /api/admin/* have `dependencies=_ADMIN` (api.py:165). Login is client-side only (frontend/src/pages/Login.tsx: the OTP step advances via setStep with no backend call).
- **Observed:** curl -s 'http://localhost:8630/api/overview?m=M18' returns M18's GMV, customer counts and funnel with no credential; _check_merchant(m) only validates that the key exists. The header merchant picker exposes all 343 keys via /api/meta.
- **Impact:** A merchant-intelligence product where merchant A can read merchant B's GMV, ticket and customer base cannot be shipped by a PSP at any price — it is a competitive-data-leak and a regulatory problem, independent of how it is hosted. Blocks the merchant surface from any pilot with real merchants.
- **Recommended fix:** Bind the session to a merchant server-side (token → merchant_key) and derive `m` from the session instead of the query string on every merchant endpoint; keep the multi-merchant picker behind the ops role only.
- **Verifier's note:** Substance is real and reachable — I reproduced it against the running server, not just by reading. But I'd assign MEDIUM, not high, for the current repo state.

Reasons the "high" framing is overstated as written:
1. It is a disclosed design decision, not an oversight. README.md:142-145 "Limitations (honest)": "Single-tenant, no enforced auth (queries already scoped)." api.py:163 carries the same comment inline, and README:74-76 documents the multi-tenant migration path (OIDC/RBAC) as deliberately not built. A known, documented scope boundary in a hackathon/challenge build is a gap, not a vulnerability being shipped unknowingly.
2. No production credential or live merchant data is exposed today — this is a local challenge dataset served from DuckDB/Parquet on localhost with no deployment surface in the repo (docker-compose is local).
3. Every query IS scoped by `m`; there is no cross-tenant SQL leak or IDOR-via-broken-filter. What is missing is the binding between an authenticated principal and the `m` parameter — i.e. authn/authz is absent, not broken. That is one dependency + one claim check away, not an architecture rewrite.

Where the finding is right and I'd keep it as a hard release gate: the claim "blocks the merchant surface from any pilot with real merchants" is correct. The moment this is hosted with real merchant data, any visitor can enumerate all 343 keys from /api/meta and read every merchant's GMV, median ticket, customer counts and funnel. So: MEDIUM now, HIGH the instant it is deployed with non-synthetic data or exposed beyond localhost. Fix is small: a `Depends` that resolves the caller's merchant claim and asserts it equals `m`, applied inside _check_merchant so all nine routes are covered by one guard.

### ZB-031 · Plain-language tooltip system is not wired into any merchant analytics page

**Lens:** `ux` · **Severity:** HIGH · **Effort:** small · **Verification:** CONFIRMED

- **Where:** frontend/src/components/Tooltip.tsx:7-29 (TIPS) vs frontend/src/pages/{Overview,FunnelPage,CustomersPage,PeersPage,ChangesPage,QualityPage}.tsx
- **Observed:** Grep for imports of Tooltip returns exactly three files: ops/OpsAI.tsx, ops/OpsPerformance.tsx and components/Copilot.tsx. No merchant analytics page imports Term. Only 5 of the 28 TIPS entries are reachable on the merchant surface (gmv, conv, customers, verify via CopilotPage.tsx:29-35 glance, plus 'deterministic' on the answer chip). Meanwhile Overview.tsx:54-59 renders bare labels «نرخ تبدیل» and «میانه مبلغ تراکنش» with only an evidence button; FunnelPage.tsx:65 says «پنجک‌های مبلغ»; FunnelPage.tsx:116 says «کد پاسخ سوییچ»; CustomersPage.tsx:60 heads a section «بازگشت مشتریان (کوهورت ماهانه)»; PeersPage.tsx:70-71 shows «میانه همتایان» and «چارک برتر»; ChangesPage.tsx:110 renders deltas as «واحد» (percentage points) with no gloss anywhere.
- **Impact:** The product's headline answer to jargon exists as content but is unreachable exactly where the jargon lives. A shop owner reading the funnel, peers or customers page hits median/quintile/quartile/cohort/percentage-point language with no explanation, which is the difference between a dashboard they trust and one they close.
- **Recommended fix:** Wrap the existing labels in <Term>: Overview KPI keys with gmv/conv/median/customers, FunnelPage stage and PSP labels with sessions/psp/noattempt/inbank, CustomersPage heading with cohort, PeersPage with peers, ChangesPage with decomp. The tips are already written — this is import + wrap, no new copy needed.
- **Verifier's note:** Substance is real and reachable, but two details in the claim are off and the severity is overstated.

1. Count is wrong: TIPS has 21 entries, not 28 (`rg -c "^  [a-z0-9]+: \{ title:" components/Tooltip.tsx` → 21). So it is 5 of 21 reachable, not 5 of 28. Still under a quarter.

2. "no gloss anywhere" is too absolute in one spot: CustomersPage.tsx:61 already explains the cohort concept inline via the Section `sub` ("هر ردیف: مشتریانی که اولین خرید موفقشان در آن ماه بود؛ ستون‌های بعدی سهم بازگشت آن‌ها در ماه‌های بعد"). And EvidenceDrawer.tsx:82 renders `ev.definition_fa` behind every «محاسبه» button, so the 19 EvBtn-backed metrics on Overview/Funnel/Peers/Changes/Customers do have a reachable Persian definition — one click deeper, not zero explanation. The genuinely unglossed cases are the ones with neither a Term nor an EvBtn: «میانه همتایان» / «چارک برتر» (PeersPage.tsx:70-71), «پنجک» (FunnelPage.tsx:65), and «واحد» from fmt.ts:29-32.

Severity I would assign: medium, not high. Nothing is broken, no wrong number is shown, no data or security path is touched — it is unshipped UX polish on the product's differentiator, and the fix is mechanical (import Term, wrap ~10 labels, all copy already written). Call it high only if "explain the jargon" is a stated launch requirement rather than a nice-to-have.

### ZB-032 · Copilot answers a different question instead of admitting it did not understand

**Lens:** `ux` · **Severity:** HIGH · **Effort:** small · **Verification:** CONFIRMED

- **Where:** zarin/copilot.py:127-131 (fallback plan) rendered by frontend/src/components/Copilot.tsx:112-120
- **Observed:** Live: GET /api/copilot?m=M156&q=آب و هوای تهران چطور است؟ returns intent:"fallback" with answer_fa = «خلاصه این بازه: فروش موفق ۱٫۹۵ هزار میلیارد ریال…» and confidence "medium". The UI renders this identically to a real answer — Copilot.tsx:113 prints answer_fa, :117 attaches the «محاسبه قطعی از داده شما» chip, :119 attaches ConfChip. `intent === "fallback"` is never checked in the component; the `fallback` field it does check (:118) is the LLM-degradation flag, not the intent.
- **Impact:** A merchant who asks anything outside the regex intents gets a confident, evidence-badged answer to a question they did not ask, and has no way to tell it was not understood. That is worse than a refusal — it teaches the merchant to trust answers that were never matched to their question.
- **Recommended fix:** When intent === "fallback", prefix the bubble with an explicit «سوال شما را دقیق متوجه نشدم — این خلاصه کسب‌وکار شماست» line and drop the confidence chip; render the six suggested questions as tappable prompt chips rather than inline text.
- **Verifier's note:** Substance confirmed, severity overstated. I'd assign **medium**, not high.

Why not high: no wrong data is shown. The KPIs in the fallback text are correct for the merchant and the period, the evidence payload genuinely backs them, and the text ends with «می‌توانید بپرسید: …» listing the six supported question shapes — a real, if weak and badly-placed, signal that the question was not matched. The claim's "has no way to tell it was not understood" is therefore an overstatement: the tell exists, it is just buried after a confident-looking summary and contradicted by the evidence badge and the medium confidence chip. There is no data leak, no fabricated number, no security or money path involved. It is a trust/UX defect in a product whose pitch is "numbers are never invented" — worth fixing, not worth paging anyone.

Cheapest correct fix is one line in copilot.py, not in the component: make the fallback plan lead with an admission and drop its confidence, e.g. return the text prefixed with «این پرسش را متوجه نشدم؛ در عوض خلاصه این بازه:» and pass "low" instead of "medium" at zarin\copilot.py:131. That fixes ops surfaces and the eval harness at the same time, whereas an `intent === "fallback"` check in Copilot.tsx:112-120 would have to be duplicated in OpsCopilotPage since both render the same shared component.

### ZB-033 · Rich tooltip is positioned by physical-right math but applied to a logical inset — mirrors across the viewport in RTL

**Lens:** `design` · **Severity:** HIGH · **Effort:** small · **Verification:** CONFIRMED

- **Where:** frontend/src/components/Tooltip.tsx:31-36, 64 (used on every KPI label, funnel chip and ops metric)
- **Observed:** pos() returns `right = window.innerWidth - r.right - 150 + r.width/2` — a distance from the *physical* right edge — and line 64 applies it as `insetInlineEnd: box.right`. The document is dir="rtl" (frontend/index.html) and .tip-pop is portaled to document.body with no direction override (theme.css:370), so inset-inline-end resolves to `left`. Worked example: a trigger at x=1000–1100 in a 1440px viewport yields 240, applied as left:240px, placing a 300px popup at 240–540 while its trigger sits at 1000–1100. As `right:240px` it would land at 900–1200, exactly centred on the trigger.
- **Impact:** The product's signature progressive-disclosure affordance (یعنی چه؟ / چرا مهم است؟ / چطور تفسیر کنم؟) detaches from the term it explains and flies to the opposite side of the screen — worst for the right-most elements, which in RTL are the primary ones. I could not render the app to confirm visually, so this is code-verified only.
- **Recommended fix:** Either compute the logical inset (`inlineEnd = r.left - 150 + r.width/2`, clamped) or keep the physical math and set `right: box.right` on a `.tip-pop { direction: rtl }` element positioned with physical properties. Add one visual check at both dir values.
- **Verifier's note:** Substance is real and reachable; I'd assign MEDIUM rather than high. It is a purely visual/UX defect — no data, correctness, or security impact, and nothing crashes. Displacement is also not uniform: the mirror is the identity at the viewport's horizontal centre, so error is zero for centred triggers and grows toward the edges (worst case, the far-right clamp collapses to 12 and pins the popup to the far left). That said, it is systematic, always-visible, un-dismissable by the user, and worst precisely on the RTL-primary right-most KPIs, which is why I'd put it at the top of medium rather than low. Two inaccuracies in the write-up that do not change the verdict: (1) scope is overstated — there are only 8 `<Term>` call sites across 3 files (Copilot.tsx, OpsPerformance.tsx, OpsAI.tsx), and pages/FunnelPage.tsx contains no `<Term>` at all, so "every KPI label, funnel chip and ops metric" is wrong about funnel chips; (2) unrelated secondary bug in the same function — the 150/320 constants hardcode a 300px popup, but theme.css:370 sets `width: min(300px, 86vw)`, so centring also drifts below ~349px viewport width. The one-line fix is to change `insetInlineEnd` to `right` at Tooltip.tsx:64 (keeping pos() as-is), not to rewrite the math.

### ZB-034 · Cohort heat map uses an absolute 0–100% colour ramp, so real retention data renders as one flat green

**Lens:** `design` · **Severity:** HIGH · **Effort:** small · **Verification:** CONFIRMED

- **Where:** frontend/src/components/charts.tsx:167 (CohortGrid); visible in docs/screenshots/rd-customers.png, «بازگشت مشتریان (کوهورت ماهانه)»
- **Observed:** alpha = min(0.08 + share * 1.6, 0.9). The live M156 cohort values in the screenshot span ۳٪–۱۱٪, mapping to alpha 0.13–0.26 — a 0.13 spread out of a 0.82 range. Every cell in the grid is visually the same pale green; ۳٪ and ۱۱٪ are indistinguishable.
- **Impact:** The heat map is the only retention visual in the product and it encodes no readable signal — a user cannot see which cohort retained better, which is the entire question the section asks ("چه کسانی می‌خرند و آیا برمی‌گردند؟"). It degrades to a plain number table with decorative tinting.
- **Recommended fix:** Normalise the ramp to the observed non-k0 max (or a p95 of observed shares) rather than 1.0, and add a small legend showing the mapped range. Keep the existing ≥4.5:1 text-colour switch, re-thresholded against the new scale.
- **Verifier's note:** Substance is real and reproducible, but I'd assign MEDIUM, not high.

Reasons to downgrade:
1. Each cell prints its own percentage as text (`pct(share, 0)`, charts.tsx:171), so no information is actually lost — the user can read that 11% beat 3%. The impact claim "a user cannot see which cohort retained better" overstates it; the correct statement is the one the finding also makes: it degrades to a number table with decorative tinting. Colour scanning is lost, values are not.
2. It is data-dependent, not universal. Across five merchants pulled from the live API: M156 alpha 0.135-0.263 and M18 0.187-0.351 (both flat, as claimed), but M250 0.263-0.879, M27 0.140-0.900 and M97 0.328-0.595 use most or all of the ramp. So the ramp is badly calibrated for low-retention merchants rather than globally broken.
3. No correctness, data, or security impact.

Related second-order defect worth folding into the same fix: the `* 1.6` with `min(..., 0.9)` cap means every share >= 51.25% clips to the identical maximum colour. M27's cells are [62.9, 6.8, 43.5, 3.7, 27.7, 76.0]% — 62.9% and 76.0% render as the same swatch. So the ramp is simultaneously too flat at the bottom and saturated at the top.

Fix is one line: replace the absolute ramp with a normalization against the grid's own max k>0 share (the component already builds the full `cell` map, so the max is free to compute alongside `maxK` at line 129), and keep a floor so a max of ~0 doesn't blow up.

### ZB-035 · Body/muted text tokens fail 1.4.3 across every surface; mobile primary nav at 2.35:1

**Lens:** `accessibility` · **Severity:** HIGH · **Effort:** small · **Verification:** CONFIRMED

- **Where:** frontend/src/theme.css:13-14 (`--ink-3:#7c7e8a`, `--ink-4:#a0a2ac`); consumers at theme.css:86 `.side-head`, :121 `.topbar .t-sub`, :142 `.bn-item`, :196 `.section > .sub`, :218 `.stat .k`, :295 `.glance .gk`, :339 `.composer-note`, :389 `.footer-note`, :429 `.entry-sub`; `.chip-good` theme.css:200
- **Observed:** Computed WCAG ratios from the literal token values: `--ink-3` #7c7e8a = 4.03:1 on `--surface` #fff, 3.73:1 on `--bg` #f6f6f7, 3.67:1 on `--surface-3`; `--ink-4` #a0a2ac = 2.54:1 on white, 2.35:1 on `--bg`. All are applied to text at 0.68–0.74rem (≈10.9–11.9px), i.e. never "large text". `.bn-item` (verified in the shipped bundle `zarin/static/assets/index-ki_7A9bP.css`: `font-size:9.5px;color:var(--ink-4)`) is the ONLY navigation on mobile — every inactive tab label sits at 2.35:1 and 9.5px, visible in docs/screenshots/rd-mobile.png. `.chip-good` (--good #0d8a5f on --good-bg #e7f6f0) = 3.91:1 for the "اطمینان بالا" confidence chip that the product's own honesty story depends on.
- **Impact:** Fails WCAG 2.1 AA 1.4.3 Contrast (Minimum) on the KPI labels, every section subtitle, the confidence chips, the sidebar group headings and the whole mobile tab bar. Low-vision and older users — a large share of a payments merchant base — cannot read the labels that give the numbers meaning, and on mobile cannot see which tab they are on beyond the bold weight.
- **Recommended fix:** Darken `--ink-3` to ≈#5f616c (4.5:1 on `--bg`) and `--ink-4` to ≈#6b6d78; never use `--ink-4` for text (reserve it for decorative dividers). Raise `--good` to ≈#0a6f4d for the `.chip-good` pairing. Raise `.bn-item` label size to ≥11px. Add a CI check that computes ratios for every token pair used on text.
- **Verifier's note:** Substance is real and reachable; severity "high" is fair for an a11y audit — I'd keep it. Two accuracy corrections worth passing on: (1) the title's "mobile primary nav at 2.35:1" uses the wrong backdrop — `.bottomnav` is `background: var(--surface)` (#ffffff, theme.css:137), so inactive tab labels are 2.54:1, not 2.35:1 (still a hard fail, and worse than the title implies relative to the 4.5 floor only in that it is the smallest text on screen at 9.5px). 2.35:1 is what `--ink-4` would be on `--bg`, which is where `.footer-note` (:389) and `.login-foot` (:173) actually sit. (2) The `--ink-3` failures are marginal (4.03 vs 4.5 on white) — a one-token darkening to roughly #6e707b clears 4.5:1 on all three surfaces; `--ink-4` and `--good`/`--good-bg` need real changes, not a nudge. `--ink-2` (#4b4d59) is fine at 8.38:1, so the fix is confined to two ink tokens plus the good chip pair.

### ZB-036 · Chat composer input has its focus indicator removed (2.4.7)

**Lens:** `accessibility` · **Severity:** HIGH · **Effort:** small · **Verification:** CONFIRMED

- **Where:** frontend/src/theme.css:326-327 `.composer input { … outline: none; }` — confirmed in shipped CSS `/assets/index-ki_7A9bP.css`
- **Observed:** The global rule `input:focus { outline: 2px solid var(--blue); outline-offset: 2px }` at theme.css:59 has specificity (0,1,1); `.composer input` is also (0,1,1) and appears later in the file, so `outline:none` wins. The composer is the chat-first landing's primary control (Copilot.tsx:146) and has no substitute indicator — `.composer form` has a static `1.5px solid #e0e0e5` border with no `:focus-within` state.
- **Impact:** Fails WCAG 2.1 AA 2.4.7 Focus Visible. A keyboard-only user tabbing to the product's headline feature — "گفتگو با زرین‌بین" — has no way to tell that the text field is focused, so they cannot know whether typing will go into the field or trigger page shortcuts.
- **Recommended fix:** Delete `outline:none` from `.composer input` and add `.composer form:focus-within { border-color: var(--blue); box-shadow: 0 0 0 2px var(--blue) }`, so the focus ring reads on the visually enclosing pill rather than the borderless input.
- **Verifier's note:** Substance is real and the cascade analysis in the finding is exactly right — this is WCAG Failure F78 (author styling removing the visual focus indicator), a genuine 2.4.7 Level AA failure on the product's primary control.

Severity: I'd assign medium, not high. The impact statement overstates the consequence. Nothing in either stylesheet touches `caret-color` (`rg -c "caret"` over theme.css and the shipped asset returns no matches), so the browser's default blinking text caret still renders when the composer input is focused. A sighted keyboard user therefore does have a weak indication that focus landed in the field — "no way to tell that the text field is focused, so they cannot know whether typing will go into the field" is stronger than the code supports. The failure is real (the caret is not an author-provided indicator meeting 2.4.7's intent, and F78 is triggered by the explicit `outline:none`), but the practical user harm is degraded discoverability rather than a total loss of focus information.

Fix is one line, no new CSS needed: delete `outline: none` from theme.css:327 and let the global rule at :59 apply, or move the ring to the wrapper with `.composer form:focus-within { outline: 2px solid var(--blue); outline-offset: 2px; }` which reads better against the rounded 16px form.

### ZB-037 · Seven zero-size, invisible buttons in the tab order on the Overview and Customers KPI strips

**Lens:** `accessibility` · **Severity:** HIGH · **Effort:** small · **Verification:** CONFIRMED

- **Where:** frontend/src/pages/Overview.tsx:44,49,54,59,63 and frontend/src/pages/CustomersPage.tsx:34,39 — `<EvBtn … label="" />`; renderer at frontend/src/components/ui.tsx:49-57
- **Observed:** `EvBtn` renders `{p.label ?? "محاسبه"}`. `label=""` is not nullish, so `??` yields the empty string and the `<button class="ev-btn">` renders with no content; `.ev-btn` (theme.css:206) is `background:none; border:0; padding:0`, giving a 0×0 box. I confirmed the exact same `label:""` calls survive in the served bundle `zarin/static/assets/index-Bx9Uu9tu.js`. The buttons remain keyboard-focusable and have only an `aria-label`. Separately, `.ev-btn` instances that DO have text ("این عدد از کجا آمد؟") are inline text ~17px tall and are excluded from the `@media (pointer: coarse)` 44px rule at theme.css:433, which covers only `.btn`, `.field`, `.composer-send`, `.mic` — as are `.seg button` (period selector, ~26px) and `.vote-btn` (~22px).
- **Impact:** Fails 2.4.7 Focus Visible — the focus ring is painted on a zero-area element, so a sighted keyboard user tabbing the Overview hits five dead stops with no visible focus anywhere. Also fails 2.4.4/2.5.3 in spirit (a control with no visible label), and the undersized real controls fail WCAG 2.2 AA 2.5.8 Target Size (24×24) / 2.1 AAA 2.5.5 on touch.
- **Recommended fix:** Change the default to `{p.label || "محاسبه"}` and give the KPI-strip variant a small visible icon (the existing `IconSearch`) inside a ≥24×24 hit area; extend the `pointer: coarse` min-height rule to `.ev-btn, .seg button, .vote-btn, .suggest button, .side-item`.
- **Verifier's note:** Primary substance is real and reachable, but I'd assign MEDIUM, not high, and two secondary claims are overstated.

Severity: it is a genuine WCAG 2.4.7 failure on the two most-visited pages (7 zero-area keyboard stops), but nothing is broken for mouse users, no data/security path is touched, and the fix is a one-token change (`p.label || "محاسبه"`, or drop the `label=""` props). Real, cheap, not high.

Overstated details:
1. "no visible focus anywhere" — `theme.css:59` sets `outline: 2px solid var(--blue); outline-offset: 2px` on `button:focus-visible`. Browsers do paint an outline on a zero-area box, so the user sees a ~4-8px blue speck, not literally nothing. Still far below a perceivable indicator, so the failure stands; the description just isn't exact.
2. The 2.5.8 (24x24 AA) claims about the *real* controls don't hold up on measurement. `.seg button` (theme.css:124) is font-size 0.72rem (~11.5px) x inherited line-height 1.75 (~20px) + 10px padding = ~30px tall. `.vote-btn` (theme.css:319) is 12px x 1.75 (~21px) + 4px padding + 2px border = ~27px. Both clear 24x24 AA; only the AAA 2.5.5 44px goal is missed, which the `@media (pointer: coarse)` rule already concedes for `.btn`/`.field`/`.composer-send`/`.mic`. Text-bearing `.ev-btn` (~20px tall) is the only borderline one, and it sits inline in a line of text, where 2.5.8's inline exception plausibly applies.

So: fix the `label=""` calls; treat the "undersized real controls" half of the finding as a nice-to-have, not a conformance failure.

### ZB-038 · Abbreviation rule accepts arbitrary downscale (۱۰۰ → ۱۰, ۱۲۰۰ → ۱۲)

**Lens:** `ai-grounding` · **Severity:** HIGH · **Effort:** small · **Verification:** CONFIRMED

- **Where:** zarin/ai/gateway.py:51 (d.startswith(x) and set(d[len(x):]) <= {"0"})
- **Observed:** Verified: is_grounded('۱۰ درصد','مقدار ۱۰۰ درصد') → True and is_grounded('۱۲','۱۲۰۰') → True. The rule targets order-of-magnitude abbreviation (618 ⇐ 61800000000 with a restated scale word) but imposes no requirement that a scale word accompany the shortened run.
- **Impact:** The LLM can present a 10x or 100x understated figure — ۱۰٪ where the engine computed ۱۰۰٪ — shown as engine truth with no hallucination_risk flag.
- **Recommended fix:** Allow the prefix rule only when the LLM run is immediately followed by a Persian scale word (میلیون/میلیارد/هزار میلیارد) whose magnitude matches the dropped zeros; otherwise require exact equality.
- **Verifier's note:** Substance is real and reachable, but severity is overstated — I'd assign MEDIUM, not high, for three reasons.

1. The headline example in the finding is not reachable in product. `fa_pct` (C:\Users\pro\OneDrive\Desktop\zarinpal\zarin\fa.py:35) always emits one decimal digit, so 100% renders as "۱۰۰٫۰٪" → run "100.0". Line 51 requires `"." not in d`, so decimals never enter the prefix rule: `is_grounded('نرخ موفقیت ۱۰ درصد بود', 'نرخ موفقیت ۱۰۰٫۰٪ بود')` → False. "۱۰٪ where the engine computed ۱۰۰٪" cannot happen via the engine's own percent formatter. The claimed `is_grounded('۱۰ درصد','مقدار ۱۰۰ درصد')` → True is true only for a hand-written bare-integer percent string the engine does not produce.

2. The live blast radius is bare integers: `fa_num` counts (customers, payments, sessions, latency ms — many call sites in copilot.py/ops_copilot.py/insights.py) and the `هزار` / sub-10k branches of `fa_money` (fa.py:29-31). Real, but narrower than "any figure".

3. Direction is one-way: `d.startswith(x)` means the LLM number must be a shortened prefix, so only understatement is possible, never inflation. And the trigger is an LLM dropping trailing digits, not attacker-controlled input.

Worth flagging alongside: the intended case the rule exists for is largely dead in product. `fa_money(61_800_000_000)` = "۶۱٫۸ میلیارد ریال" (decimal), so the "618 ⇐ 61800000000" abbreviation only fires when a raw `fa_num` of a large figure reaches the deterministic text — tests\test_ai.py:130 vs :134 shows exactly this split. In practice the prefix branch's main live effect is the false-accept, which makes tightening it cheap: require the abbreviated run to be accompanied by a scale word, or drop the branch and let `fa_money`'s decimal form carry the abbreviation.

### ZB-039 · Guard is unit- and metric-blind: same digits, wrong currency or wrong metric passes

**Lens:** `ai-grounding` · **Severity:** HIGH · **Effort:** medium · **Verification:** CONFIRMED

- **Where:** zarin/ai/gateway.py:43-60
- **Observed:** Against det «فروش موفق ۱٫۹۵ هزار میلیارد ریال … نرخ تبدیل ۵۴٫۵٪، ۲۳،۸۰۱ مشتری», both «فروش شما ۱٫۹۵ هزار میلیارد تومان بود» (10x, Rial→Toman) and «نرخ تبدیل شما ۳۰،۵۰۸ درصد و ۵۴٫۵ مشتری داشتید» (numbers swapped between metrics) returned is_grounded=True. Single-digit runs are skipped entirely (gateway.py:40), so «۳ برابر ماه قبل» and «۹ درصد رشد» are free inventions that also pass.
- **Impact:** Rial/Toman confusion is the canonical Persian money error and the guard is exactly blind to it; a number reattached to the wrong metric reads as a precise engine-backed claim. Both are silent — telemetry records them as grounded.
- **Recommended fix:** Match (number, unit/metric-word) pairs rather than bare digit runs: require each LLM run to carry the same trailing unit token (ریال/درصد/مشتری/پرداخت/میلیارد) as in the deterministic text, and drop the >=2-significant-digit exemption for runs adjacent to a unit or multiplier word (برابر، درصد).
- **Verifier's note:** Severity high is correct, but one piece of the reviewer's cited evidence does not reproduce and should be corrected in the report: their metric-swap example «نرخ تبدیل شما ۳۰،۵۰۸ درصد و ۵۴٫۵ مشتری داشتید» actually returns is_grounded=False, because 30508 is not among the det runs — the guard catches that one. The metric-swap claim is nonetheless real: substituting the actual det number (۲۳،۸۰۱ as a percentage, ۵۴٫۵ as a customer count) passes with grounded=True. So the finding's substance survives, its example does not.

Second nuance: the single-digit skip at gateway.py:40 is deliberate and commented ("skip ordinals"), so that sub-claim is a documented tradeoff rather than an oversight — though the comment understates its blast radius, since «۳ برابر ماه قبل» and «۹ درصد رشد» are precisely the shape of claim a rephrasing model invents, and they are free.

Severity rationale for keeping high rather than medium: Rial/Toman is not a speculative failure mode. Persian speakers colloquially quote money in تومان, so a model told to rewrite into "فارسیِ ساده و دوستانه" (_SYSTEM_PROMPT, gateway.py:21) faces active linguistic pressure to convert, and the guard is structurally blind to it — it compares digits, and the digits are identical. The module docstring's promise at gateway.py:6, "The numbers a merchant sees are therefore always the engine's, never the model's," is true of the digits and false of the quantities, on a payments product where the error is exactly 10x.

### ZB-040 · "Refusal safety 100%" is vacuous — the checks cannot fail and the cases do not refuse

**Lens:** `ai-grounding` · **Severity:** HIGH · **Effort:** medium · **Verification:** CONFIRMED

- **Where:** zarin/ai/eval/runner.py:22 (no_forbidden), zarin/ai/eval/cases.py:37-40, surfaced as «ایمنی در نبود داده» in frontend/src/ops/OpsAI.tsx:72
- **Observed:** `uv run python -m zarin.ai.eval` prints refusal safety 100% (12/12 passed). But _plan() never echoes user text — every branch returns a fixed template — so forbid_substrings=["تبلیغات"] can never trip. And the refusal cases do not refuse: live, «فروش من ماه آینده چقدر می‌شود؟», «نرخ ارز فردا چقدر می‌شود؟» and «شماره کارت مشتری‌ها را بده» all return the generic GMV/conversion summary at confidence=medium.
- **Impact:** The Control Center shows a 100% bar labelled «آیا هنگام کمبود داده به‌جای ساختن عدد، صادقانه امتناع کرد و علیت جعلی نساخت؟» for a property the system does not have; an operator would wrongly conclude out-of-scope handling is verified.
- **Recommended fix:** Add an explicit out_of_scope branch to _plan() (forecasting, PII/card data, unsupported metrics, greetings) that declines and names what it can answer, then make refusal cases assert intent==out_of_scope and confidence=low. Until then, relabel or drop the indicator.
- **Verifier's note:** Substance fully confirmed, and the reviewer understated one detail: the «تبلیغات» case does not merely fail to refuse, it answers at confidence=high with a full causal attribution — exactly the "invented causality" the tooltip claims was excluded. Severity: I'd keep it high. It is not a data-safety or correctness defect in merchant-facing numbers (those stay grounded, and «شماره کارت» leaks nothing — it just ignores the request), so by runtime blast radius alone it is medium. But the defect is a false assurance sitting in the one panel whose stated purpose is honest measurement ("never one meaningless score"), and it is the kind of green bar an operator uses to conclude out-of-scope handling is verified. Cheapest real fix: score refusal_safety on an assertion that can fail — e.g. require intent=="fallback" plus confidence=="low" for out-of-scope cases, which currently fails for all three of them.

### ZB-041 · LMDI and conversion-driver tests assert closure, not attribution — a factor swap stays green

**Lens:** `testing-qa` · **Severity:** HIGH · **Effort:** small · **Verification:** CONFIRMED

- **Where:** tests/test_metrics.py:81-94; zarin/analytics.py:236-242
- **Observed:** test_lmdi_decomposition_is_exact asserts only `abs(sum(contrib) - delta_gmv) < 1e-6`, and test_conv_drivers_sum_to_conv_change asserts only `abs(sum(conv_drivers) - dconv) < 1e-9` plus that `reversed_rate` is non-zero. Closure is a mathematical property of `_lmdi_contrib` (analytics.py:236-242) that holds for *any* assignment of factor series to labels. In the M1 fixture Jan→Feb all three factors move (sessions 7→2, conv 3/7→1/2, ticket 200k→400k), so relabelling `sessions` as `ticket` would still sum exactly to ΔGMV.
- **Impact:** The what-changed decomposition is the product's causal narrative. A refactor that mis-wires which series feeds which factor would attribute a sales drop to the wrong cause — telling a merchant to fix traffic when the real cause was conversion — with a fully green suite.
- **Recommended fix:** Add a fixture window where exactly one factor moves and assert its contribution ≈ ΔGMV with the others ≈ 0; add a sign/dominance assertion on the mixed window (e.g. contrib['ticket'] > 0 and |contrib['sessions']| is the largest term).
- **Verifier's note:** Substance is real and precisely stated; I'd downgrade severity from high to MEDIUM. The current wiring at analytics.py:259-261 is correct — this is a latent regression risk (missing discriminating coverage), not a shipping defect, and it needs a future refactor to become merchant-visible. The finding's own framing ("a refactor that mis-wires…") concedes this.

Two additions the finding understates. (1) The conv_drivers gap is worse than described: in the M1 fixture `no_attempt_rate`, `inbank_abandon_rate`, `failed_bank_rate` and `paid_unverified_rate` all evaluate to exactly 0.14285714285714285, so even a value-level assertion on those four would not discriminate a swap among them — only `reversed_rate` (-0.5) is separable, and the test checks just its presence and non-zero-ness. Fixing this needs a fixture change, not only a test change. (2) `test_lmdi_decomposition_is_exact` is the cheaper fix: the three contribs are already distinct in sign and magnitude, so pinning `contrib["sessions"] < 0 < contrib["ticket"]` (sessions fell 7→2 while ticket doubled) closes it in one line with no fixture work.

### ZB-042 · Insights engine at 55% — six of nine card generators never run, incl. the PSP selection-bias fix

**Lens:** `testing-qa` · **Severity:** HIGH · **Effort:** medium · **Verification:** CONFIRMED

- **Where:** zarin/insights.py:164-222, 241-250, 275-288, 292-294, 320-343, 370-386
- **Observed:** 70 of 156 statements uncovered. The fixture merchants are below MIN_SESSIONS_INSIGHT (100), so the `if me["sessions"] >= MIN_SESSIONS_INSIGHT` gate at insights.py:162 short-circuits everything. recovery_gap (180-205), high_value_friction (208-236), repeat_gap (241-265), concentration (275-288), _psp_card (318-343) and _change_alert (370-386) are all dead in tests; only `_gap_card` is called directly with synthetic input. Commit 58ba5ca claims a 'PSP selection-bias guard' fix — the guard `ok_rate >= 0.05 and successes >= 30` at insights.py:329 has no regression test. Live `curl /api/insights?m=M156` returns four cards (paid_unverified 61.8e9, inbank_gap 45.8e9, psp_friction 214, gmv_change alert) — every one of them from an untested branch, and the ranking rule at insights.py:303-314 that must keep opportunities above alerts is never exercised with a mixed card set.
- **Impact:** The ranked action cards are the product's primary output. A regression that reintroduces phantom PSP opportunities from a disabled rail, or that lets a zero-impact 'sales grew' alert outrank a real 61.8B rial opportunity, ships silently.
- **Recommended fix:** Add a large-merchant fixture (≥100 sessions, ≥2 PSPs with divergent success rates, one degenerate ~0% rail) and assert: psp_friction excludes the degenerate rail; cards sort opportunities-before-alerts with score descending; each generator's impact band is monotone in the gap.
- **Verifier's note:** Substance confirmed and, if anything, understated — with one factual correction.

CORRECTION: `_change_alert` is NOT dead. It runs end-to-end (29/37 exec-lines; card body 401-413 hit; appended at line 299). The finding lists it among the six dead generators — that item is wrong. But `paid_unverified` (146-160, hit=1) IS dead and the finding omits it, so the headline count still holds. Recounted properly: of the nine card generators, only `gmv_change` runs end-to-end and only `_gap_card`'s shared math is exercised (directly, with synthetic input, in tests/test_insights_peers.py:36-73). Eight of nine card-construction bodies never execute — worse than the "six of nine" claimed.

SEVERITY: I would assign medium-high rather than high. This is a pure coverage gap, not a demonstrated defect: the PSP guard at insights.py:329 (`ok_rate >= 0.05 and successes >= 30`) reads correctly, and the live M156 response looks sane (opportunities ranked above the alert, psp_friction flagged `impact_is_count: True` so its 356 is transactions not rials). Nothing is currently broken. What is real is the regression exposure — every card the product actually ships is generated by an untested branch, the specific bug 58ba5ca claims to have fixed has zero regression test, and the ranking invariant the module docstring calls out at line 301-302 has never been executed with an opportunity in the list. High would be right if a live defect existed; medium-high is right for "correct today, unguarded tomorrow."

CHEAPEST FIX (not applied — read-only task): the blocker is fixture size, not test design. One synthetic merchant in tests/conftest.py with >=100 sessions, >=200 attempts across two psp_codes (one at ~0% success to trip the 329 guard, one healthy), would light up recovery_gap, high_value_friction, psp_friction and the opportunity ranking branch in a single fixture addition. A separate 3-line unit test calling `generate`'s ranking on a hand-built mixed card list covers 306-314 without any fixture work at all.

### ZB-043 · No frontend tests at all; Persian formatting is duplicated between fa.py and fmt.ts with an observable divergence and no parity test

**Lens:** `testing-qa` · **Severity:** HIGH · **Effort:** large · **Verification:** CONFIRMED

- **Where:** frontend/package.json (no test script/runner); frontend/src/fmt.ts:23-26 vs zarin/fa.py:35-38
- **Observed:** 2,341 LOC of TS/TSX across 20 files (App.tsx, ctx.tsx, api.ts, fmt.ts, 8 pages, 5 ops pages, 6 components) with zero test files, no vitest/jest, and no eslint — the only gate is `tsc --noEmit` in the build script. fmt.ts re-implements fa.py's compact-rial and percent logic independently; they already differ: `fa_pct` uses `f"{v*100:.1f}"` so 50% renders '۵۰٫۰٪', while `pct()` uses Intl maximumFractionDigits so the same value renders '۵۰٪'. Nothing tests either implementation or their agreement.
- **Impact:** Chart axes, KPI tiles, evidence drawers and the funnel are unverified; a rial-magnitude or thousands-separator regression in fmt.ts would display a wrong-looking figure next to a correctly formatted copilot sentence from fa.py, and no gate catches it. All the a11y/mobile fixes in commits 959af02 and 4e0d0c3 are equally unprotected.
- **Recommended fix:** Add vitest with unit tests for fmt.ts (rial magnitude boundaries 1e4/1e6/1e9/1e12, pct/pp signs, localizeDates) asserted against the same expected strings as zarin/fa.py, plus React Testing Library smoke tests for Overview, InsightCard and EvidenceDrawer (loading/error/empty states). Add eslint + jsx-a11y.
- **Verifier's note:** Substance fully confirmed and if anything understated (3 divergences, not 1; the thousands-separator case the claim framed as a hypothetical future risk is already shipping). Two trivial inaccuracies, neither load-bearing: the file count is 23 TS/TSX not 20 (LOC of 2,341 is exact), and "nothing tests either implementation" should be softened to "no test asserts either implementation's output" — test_ai.py does import the fa.py helpers, but only as fixture inputs where they appear on both sides of the assertion, so they pin nothing.

Severity: I would assign MEDIUM, not high. The structural gap is genuine — 2,341 LOC of a product whose entire value proposition is displayed Persian numbers, gated only by `tsc --noEmit`, with no runner and no linter — and the divergences are real, reachable, and visible side-by-side within a single InsightCard. But every confirmed divergence is cosmetic: trailing zeros and a separator glyph. No magnitude is wrong, no value is incorrect, nothing is corrupted, and there is no security or data-loss dimension. The claim's own impact sentence ("a rial-magnitude or thousands-separator regression WOULD display a wrong-looking figure") is conditional for the magnitude half — that class of bug is possible but not currently present. High should be reserved for a defect that produces an incorrect number, not an inconsistently formatted correct one.

Cheapest fix consistent with the codebase, if wanted: delete the duplication rather than test it. Have fa.py emit the Intl-compatible forms (use U+066C and strip trailing zeros), or have the server send raw numbers and let fmt.ts do all formatting — one formatter means no parity test is needed at all. Adding vitest plus a parity fixture is the more expensive option and locks in the duplication it is testing.

### ZB-044 · Ops copilot intent routing is 54% covered and misroutes — verified, with no equivalent to the merchant copilot's ordering regression test

**Lens:** `testing-qa` · **Severity:** HIGH · **Effort:** small

- **Where:** zarin/ops_copilot.py:33-111; tests/test_control.py:68-80
- **Observed:** 46 of 99 statements uncovered (lines 36-43, 46-52, 55-60, 64-70, 83-92, 106, 115-123). Eight first-match-wins regexes; tests exercise only `system` and `sources` plus one loose ai probe. Verified in-process: `ops_copilot._plan('هزینه سرور بالا رفته چرا؟')` → intent `ai_cost` (a server-cost question routed to AI-model spend), and `_plan('چند درصد پاسخ ها مستند بوده و هزینه چقدر شده؟')` → `ai_cost`, swallowing the `ai_grounded` intent. Cause: the bare `|هزینه` alternative at ops_copilot.py:45 matches any question containing the word and sits above ai_model/ai_grounded/ai_health. The merchant copilot has a dedicated guard for exactly this class of bug (tests/test_ai.py:138-145, recovery must not be swallowed by friction); the ops copilot has none, and `_attention` (114-123) is never invoked.
- **Impact:** An operator asking about grounding rate or infrastructure cost gets an unrelated AI-spend answer with 'high' confidence and mismatched evidence. Adding or broadening any ops regex can silently capture a sibling intent.
- **Recommended fix:** Parametrize a routing table test over all eight ops intents (one representative question each, plus two compound questions asserting the more specific intent wins) mirroring test_ai.py:138, and anchor the cost regex so it requires an AI/model qualifier.

## MEDIUM severity

### ZB-045 · Data-quality page shows 1 anomaly next to a hardcoded claim of 28 for what reads as the same anomaly

**Lens:** `rubric-official` · **Severity:** MEDIUM · **Effort:** small

- **Where:** zarin/api.py:243-246 (computed) vs zarin/api.py:256 (rules_fa prose); rendered adjacent in frontend/src/pages/QualityPage.tsx:52 and :61
- **Observed:** /api/quality returns anomalies.verified_wo_ok_try = 1, rendered as «۱ جلسه Verified بدون تلاش موفق ثبت‌شده». The rules list directly below it renders the hardcoded «۲۸ جلسه Verified بدون تلاش Verified». I reproduced both against the marts: no-OK-try = 1, no-Verified-try = 28 (Paid counts as OK in the computed query). Both are correct under their own definitions; neither definition is stated.
- **Impact:** On the page whose entire purpose is analytical honesty, two different numbers for a similarly-worded anomaly appear inches apart, one of them a literal string that will drift from the data on any dataset change.
- **Recommended fix:** Compute both counts in the anomalies query with distinct labels («بدون هیچ تلاش موفق» vs «بدون تلاش Verified») and delete the hardcoded 28 from rules_fa.

### ZB-046 · Five dataset dimensions are carried into the marts and used by zero analytics

**Lens:** `rubric-official` · **Severity:** MEDIUM · **Effort:** medium

- **Where:** zarin/pipeline.py:82 (win_bank), :98 (dow), :105-106 (issuer_bank_code, init_time_ms), :72 (verify_type) — no reference in zarin/analytics.py, insights.py, peers.py or any frontend page
- **Observed:** Grep across zarin/ and frontend/src/ finds these columns only in pipeline.py and the one-off pipeline/audit*.py scripts. issuer_bank_code exists on every attempt row and is audited (pipeline/audit.py:80 shows per-bank success counts), but no insight, funnel breakdown or benchmark segments by it. init_time_ms (gateway init latency) is likewise materialized and unused; dow is computed on every session and never grouped by.
- **Impact:** Costs the depth criterion directly. Issuer-bank × PSP failure segmentation ("cards from bank X fail 3× more on your worst gateway") and init-latency → abandonment are the two most actionable relationships this schema supports, and both are absent — while the copilot fallback proves merchants will ask the day-of-week question.
- **Recommended fix:** Add one segmentation card following the _psp_card pattern: per issuer_bank_code within-merchant ok_rate with the same degenerate-rail guard, naming the worst bank and its top switch_response_codes. It reuses existing SQL shape and adds a genuinely new lever.

### ZB-047 · Peer gaps produce rial figures with no significance test; the "uncertainty" band is a hardcoded judgement constant

**Lens:** `rubric-official` · **Severity:** MEDIUM · **Effort:** medium

- **Where:** zarin/insights.py:66 (2pp threshold), :80-82 (recovery_fraction 0.5/0.75/1.0), zarin/peers.py:109-117 (percentile by raw rank)
- **Observed:** _gap_card fires on any gap ≥ 2pp with ≥5 peers and no test of whether that gap is distinguishable from peer dispersion. M156's inbank_gap fires on 5 peers (confidence "low") and still prints 98.2B–196.4B IRR. The band width comes entirely from the fixed [0.5, 0.75, 1.0] constants, so it conveys no information about peer variance or sample size. Peer percentile is exact rank, which is correct, but n=5 makes it coarse (the UI does warn via the low_n chip).
- **Impact:** The rubric asks for "uncertainty where relevant". The product is honest that the band is a scenario, not a CI — but that means no card carries statistical uncertainty at all, and a thin-peer gap and a 22-peer gap produce visually identical claims apart from a chip.
- **Recommended fix:** Gate the card on the gap exceeding peer IQR or a bootstrap CI of the peer median rather than a flat 2pp, and widen the recovery-fraction band as n_peers falls so the interval visibly reflects evidence strength.

### ZB-048 · Actions are per-kind templates that ignore what sibling cards already computed

**Lens:** `rubric-official` · **Severity:** MEDIUM · **Effort:** small

- **Where:** zarin/insights.py:175 (inbank action_fa), :167 (no_attempt action_fa) vs :350 (_psp_card action_fa)
- **Observed:** Every merchant with an inbank_gap receives the identical sentence «با پشتیبانی زرین‌پال درباره درگاه/PSP جایگزین صحبت کنید» — including M156, whose psp_friction card in the same response already identifies PSP-03 at 20.5% vs PSP-04 at 59.4% and lists its top three error codes. Only the numbers in observation_fa vary between merchants; diagnosis_fa and action_fa are constants per kind.
- **Impact:** Weakens the "concrete thing the merchant can do" half of the top criterion. The strongest evidence the engine produced is available but not wired into the recommendation the merchant actually reads.
- **Recommended fix:** When _psp_card fires, interpolate the named worst gateway into the inbank_gap action ("ask ZarinPal to shift traffic away from PSP-03"); similarly reference the amount band or hour bucket when those generators fire alongside.

### ZB-049 · DataSourceAdapter is half a nominal abstraction — the ingestion half has no production consumer

**Lens:** `architecture` · **Severity:** MEDIUM · **Effort:** medium

- **Where:** zarin/sources/base.py:32 (metrics), zarin/sources/ga4.py:47, zarin/control.py:110-116
- **Observed:** Grepped every call site: `adapter.metrics(f,t)` is invoked only from tests/test_sources.py:12,26 — never from production code. `control.sources()` calls only `.status()`. `registry()` constructs `GA4Adapter()` with no `fetch_fn`, so even a fully configured GA4 reports status="error", "no GA4 transport wired". `control.py:116` hardcodes `"cross_source_insights": []`, so the 68 lines of `sources/insights.py` are unreachable from the API.
- **Impact:** ADR-0004 claims "Adding Shopify = one adapter file; the engine and UI generalize", but today the interface only feeds a status panel. A second real source would have to invent the wiring from `metrics()` into the semantic layer from scratch, so the abstraction is not yet proof that the seam works — it is a shape without a consumer.
- **Recommended fix:** Either wire it end-to-end for one window (call `.metrics(f,t)` on connected adapters in `control.sources()` and feed the pair into `cross_source()`, so the path is exercised), or drop `metrics()` and `sources/insights.py` and keep the honest status registry. Half-wired is the worst of both.

### ZB-050 · Admin auth seam exists only on the server; the ops UI can never satisfy it

**Lens:** `architecture` · **Severity:** MEDIUM · **Effort:** small

- **Where:** zarin/api.py:34-37 (_admin_guard) vs frontend/src/ctx.tsx:78-95 (useAdmin)
- **Observed:** `_admin_guard` enforces `X-Admin-Token` via hmac.compare_digest when ZARIN_ADMIN_TOKEN is set. `useAdmin` calls `get(path, ...)` and `api.ts:164` issues a bare `fetch` with no headers argument — I grepped the whole frontend and no file references X-Admin-Token or any token. docs/DEPLOYMENT_SPEC.md:86 acknowledges it ("the ops UI must send…").
- **Impact:** Setting the token makes every Control Center page 401 and the surface unusable; leaving it unset leaves /api/admin/* fully open. The dual-surface separation is therefore purely client-side (a sessionStorage flag in App.tsx:161 plus a data-workspace attribute) with no server-side notion of surface — the security seam is one-sided, so in practice it is always in the open configuration.
- **Recommended fix:** Have Login capture the operator token for the ops path, keep it in the AppProvider, and add an optional headers argument to `get()` that `useAdmin` populates. ~15 lines and the existing guard becomes usable.

### ZB-051 · insights.py is the god module: 9 hand-built card dicts with an implicit, drifting contract

**Lens:** `architecture` · **Severity:** MEDIUM · **Effort:** medium

- **Where:** zarin/insights.py:135-315 (generate)
- **Observed:** 413 lines, the largest module in the codebase. `generate()` inlines nine card literals with ~20 duplicated keys each. The card contract is implicit and inconsistent: only `_gap_card` emits `impact_mid` (line 112), only PSP emits `impact_is_count` (line 353), only alerts emit `risk_gmv` (line 284) — and the ranking at line 303-314 depends on `card_type` being set correctly, patched by a `setdefault` at line 304. Also `from .peers import _quantile` (line 16) imports a private helper across a module boundary, and `from .db import q` is re-imported inside functions at lines 320 and 370 despite `q1` already being imported at line 14 (no cycle exists — I checked the whole graph).
- **Impact:** Adding the tenth insight means copying ~25 lines and remembering an undocumented key set; the frontend (api.ts:29-36) already carries five optional fields to absorb the variance. This is where feature growth will actually land, and it is the least structured part of the backend.
- **Recommended fix:** Introduce a frozen `Card` dataclass with the full field set and a `to_dict()`, so each generator returns a typed object and the ranking reads declared fields. Promote `_quantile` to a shared helper (it is used by two modules), and hoist the deferred `from .db import q`.

### ZB-052 · Ops surface bypasses the metric registry with hand-written evidence payloads

**Lens:** `architecture` · **Severity:** MEDIUM · **Effort:** medium

- **Where:** zarin/ops_copilot.py:24-29 (_ev)
- **Observed:** `_ev()` hand-constructs a dict shaped like `registry.evidence()` output — same keys, `metric_id: "ops"` which is not in REGISTRY — with name/definition/formula written inline per answer. `control.py:80-98` (_platform_insights) likewise hand-writes cards with no registry reference. registry.py:6 states "Nothing is hand-written per UI card."
- **Impact:** The single-source-of-truth guarantee holds for the merchant surface but not the operations surface. Ops metric definitions (fallback rate, grounded rate, cost per request) live as prose inside the copilot planner, so they can drift from what OpsAI.tsx labels the same numbers, and none of them get caveats or the drawer's traceability treatment.
- **Recommended fix:** Add the ~8 platform/telemetry metrics to REGISTRY with grain="platform" and have ops_copilot call `evidence()` with sql_kind="method". Deletes _ev() and makes the claim in registry.py true for both surfaces.

### ZB-053 · Analytical thresholds live as inline magic numbers, contradicting config.py's «One source of truth», and are re-hardcoded in UI copy

**Lens:** `code-quality` · **Severity:** MEDIUM · **Effort:** medium

- **Where:** zarin/config.py:1 / zarin/insights.py:28-32,66,80-82,90,187,218,247,274,329,334,342 / frontend/src/pages/FunnelPage.tsx:82,112 / frontend/src/components/InsightCard.tsx:49
- **Observed:** config.py's docstring says «Central configuration: paths, thresholds, constants. One source of truth», and holds 5 thresholds. But `insights.py` hardcodes the 2pp gap floor (`gap_mid < 0.02`), the recovery band (`0.5/0.75/1.0`), the broken-funnel cut (`mine > 0.5`), the confidence ladder (`2000`/`500`/`8`/`5`), the recovery gap floor (`0.03`), the high-value gap (`0.05`), PSP attempt floor (`200`), success floor (`30`), concentration cut (`0.4`), «top 5» customers, and the 27-day window. Separately, `FunnelPage.tsx:82` states «حداقل ۳۰ جلسه» and `:112` «حداقل ۳۰ تلاش» (duplicating `MIN_SEGMENT_N=30`), and `InsightCard.tsx:49` gates the uncertainty chip on `card.n_peers < 8` (duplicating `PREFERRED_PEERS=8`, also hardcoded at `insights.py:96,104`).
- **Impact:** Tuning any threshold requires finding every literal across three layers; the UI copy will silently state a number the backend no longer uses, which in a product whose whole pitch is auditable numbers is a correctness-of-claim bug, not just style.
- **Recommended fix:** Move the insight thresholds into config.py next to the existing `MIN_*` block; expose `MIN_SEGMENT_N`/`PREFERRED_PEERS` through `/api/meta` (or the existing `low_n`/`n_peers` flags) so the frontend renders the server's number instead of a literal.

### ZB-054 · Top-5 concentration is implemented four times with divergent null handling

**Lens:** `code-quality` · **Severity:** MEDIUM · **Effort:** small

- **Where:** zarin/analytics.py:182-187, zarin/insights.py:268-273, zarin/control.py:42-47, zarin/api.py:240-242
- **Observed:** Four near-identical `row_number() OVER (ORDER BY gmv DESC)` + `sum(...) FILTER (WHERE rk<=5)` CTEs. Three guard the denominator with `nullif(sum(...),0)`; `api.py:242` writes `sum(gmv) FILTER (WHERE rk<=5)/sum(gmv)` with no `nullif`. `control.py:45` adds `NULLS LAST` the others omit, and the result key differs (`top5_share` in analytics, `top5` in the other three) — the frontend type `Customers.concentration.top5_share` vs `Quality.concentration.top5` reflects the split.
- **Impact:** The same business concept has four definitions in a codebase whose README claims one shared semantic layer; the `api.py` copy will divide by zero/NULL on an empty window, and a future fix to the metric will land in one to three of the four sites.
- **Recommended fix:** Extract one `concentration_top5(where_sql, params)` helper in `analytics.py` (or the registry module) and call it from all four sites, returning a single key name.

### ZB-055 · Chart colors bypass the design tokens and have already drifted

**Lens:** `code-quality` · **Severity:** MEDIUM · **Effort:** small

- **Where:** frontend/src/components/charts.tsx:4-5,19,21,25 vs frontend/src/theme.css:11,15,19
- **Observed:** `charts.tsx` hardcodes `INK = "#1c1c22"`, `YELLOW = "#ffd900"`, and `stroke="#e4e4e7"` (×3). theme.css defines `--ink: #16161d`, `--brand: #ffd500`, `--line: #e7e7ea`. These are three *different* values, not aliases — the chart palette has already diverged from the system it is supposed to match. Elsewhere the same file correctly uses `var(--good)`, `var(--ink-3)`, `var(--surface-2)` (lines 71, 112, 167).
- **Impact:** Charts render slightly off-brand today and will not follow any future token change; the mixed convention inside a single file means a maintainer cannot tell which mechanism is authoritative. (Related: ~150 inline `style={{…}}` objects across 18 tsx files carry raw pixel magic numbers — `minWidth: 84`, `width: 70`, `fontSize: 9` — alongside a 436-line token system.)
- **Recommended fix:** Read the three values once via `getComputedStyle(document.documentElement).getPropertyValue('--brand')` (or export them from a single `tokens.ts` that theme.css and charts share) and delete the literals.

### ZB-056 · No lint or test gate on 2,777 lines of frontend; `eslint-disable` comments reference a linter that isn't installed

**Lens:** `code-quality` · **Severity:** MEDIUM · **Effort:** medium

- **Where:** frontend/package.json:8-12 (scripts/devDependencies), frontend/src/ctx.tsx:92,112, frontend/src/components/EvidenceDrawer.tsx:23, frontend/src/components/Copilot.tsx:10
- **Observed:** `frontend/package.json` has no eslint, no vitest, no test script; `build` is `tsc --noEmit && vite build`. Yet four files carry `// eslint-disable-next-line react-hooks/exhaustive-deps` and `@typescript-eslint/no-explicit-any` directives — inert comments for a tool that is not in the tree (no `.eslintrc*`, confirmed by `ls frontend/`). tsconfig is `strict: true` + `noUnusedLocals` but omits `noUncheckedIndexedAccess`, so patterns like `items[0]`/`items[items.length-1]` (EvidenceDrawer.tsx:37) type as non-optional.
- **Impact:** The hook-dependency suppressions in `ctx.tsx:92,112` are exactly the pattern that needs a linter to stay honest (the `key = JSON.stringify(...)` trick is correct today but nothing enforces it); the backend has 56 hermetic tests while the UI has zero automated checks beyond type-checking.
- **Recommended fix:** Add eslint + `eslint-plugin-react-hooks` and a `lint` script (the disables then become meaningful), and enable `noUncheckedIndexedAccess`; a handful of vitest tests on `fmt.ts` (`rial`, `pct`, `deltaPct`) would cover the highest-risk pure logic cheaply.

### ZB-057 · Data Quality page contradicts itself on the known-anomaly count (1 vs 28)

**Lens:** `data-correctness` · **Severity:** MEDIUM · **Effort:** small

- **Where:** zarin/api.py:243-246 (`verified_wo_ok_try`) and api.py:256 (rules_fa), rendered together in frontend/src/pages/QualityPage.tsx:52 and :61
- **Observed:** GET /api/quality returns anomalies.verified_wo_ok_try = 1, because the SQL filters `sum(ok::int)=0` where ok = try_status IN ('Verified','Paid'). The rules list on the same card hard-codes «۲۸ جلسه Verified بدون تلاش Verified», and docs/DATA_AUDIT.md:61,79 audits exactly 28. Direct query confirms 28 Verified sessions have no try_status='Verified' row, carrying 43,815,600 IRR — precisely the session-vs-attempt GMV reconciliation gap that pipeline.py:204-205 attributes to those 28. Secondary: DATA_AUDIT.md:79 claims the payer card stays null for these; that holds for only 1 of the 28 (the other 27 have a Paid try that supplies a card).
- **Impact:** On the one page whose whole purpose is «بدون ترمیم پنهان، بدون عدد ساختگی», two numbers for the same anomaly appear four lines apart, and the surfaced one undercounts the real anomaly 28×. It also silently hides the 43.8M IRR of GMV that has no attempt-level backing.
- **Recommended fix:** Change the subquery to `HAVING sum((try_status='Verified')::int)=0` so the reported count matches the audit and the GMV gap, or rename the field/label to 'no settled attempt' and add a second counter for the 28. Either way derive the rules_fa number from the query instead of hard-coding it.

### ZB-058 · Broken-funnel branch overrides the documented small-peer-pool confidence cap

**Lens:** `data-correctness` · **Severity:** MEDIUM · **Effort:** small

- **Where:** zarin/insights.py:96-101 (`conf = "low" if n_peers < 8` … then `if broken: conf = "high"`)
- **Observed:** Live GET /api/insights?m=M265: the top card is no_attempt_gap with confidence="high", n_peers=5, broken=true, capped=true, impact 4,355,020,000 IRR. GET /api/peers?m=M265 shows the group is level="category" with n=5 — the scale/ticket comparability rules were dropped entirely. docs/ANALYTICS.md:75-76 states that with fewer than 8 peers confidence is capped at «پایین».
- **Impact:** A rial estimate whose only baseline is a 5-merchant category median is chipped 'high confidence', and CONF_W['high']=1.0 vs 0.35 inflates its ranking score ~2.9×. The 'this stage is broken' judgement is high-confidence (it comes from the merchant's own 94% NoAttempt rate), but the number displayed next to the chip is not.
- **Recommended fix:** Split the two claims: keep the broken-funnel reframing and its urgency, but leave `confidence` bound by the peer-pool rule, or add a separate `severity` field for the broken flag so confidence keeps describing the estimate. The n_peers<8 warning chip already renders (InsightCard.tsx:49-51), so only the chip and the score weight need fixing.

### ZB-059 · Peer pool includes structurally dead merchants, so the "peer median" is not a comparable baseline

**Lens:** `statistics` · **Severity:** MEDIUM · **Effort:** small

- **Where:** zarin/peers.py:17 (POOL_SQL), peers.py:64-74; merchant_stats probe
- **Observed:** POOL_SQL filters only `sessions >= 500`. Of the 81 merchants in the pool, 6 have no_attempt_rate > 0.5 and 4 exceed 0.8 — including M91 at exactly 1.000 (3,393 sessions, zero payment attempts ever) and M144 at 0.983. M156's peer group falls back to level="category" with exactly 5 peers, one of which is M265 at 0.944; its peer values are [0.044, 0.059, 0.093, 0.122, 0.944]. Dropping the dead merchant moves the median from 0.093 to 0.076. This contradicts insights.py:326-329, which excludes degenerate PSP rails with a written selection-bias rationale.
- **Impact:** At the MIN_PEERS floor of 5, one dead-integration merchant shifts the median a full rank position and can flip the 2pp card trigger either way — suppressing a real opportunity or manufacturing one. The advertised baseline ("what a comparable business achieves") is contaminated by businesses that are not transacting at all.
- **Recommended fix:** Apply the PSP degeneracy rule to the peer pool (e.g. require verified/sessions above a floor, or no_attempt_rate ≤ 0.6) and document it in docs/ANALYTICS.md §3; alternatively use a trimmed median and expose the peer values in the evidence drawer so contamination is visible.

### ZB-060 · Realized-GMV cap collapses the honest band into a point estimate equal to the merchant's entire GMV, at max confidence weight

**Lens:** `statistics` · **Severity:** MEDIUM · **Effort:** small

- **Where:** zarin/insights.py:88-100, 307; live /api/insights?m=M265
- **Observed:** When capped, `hi = realized` and `lo, mid = min(lo, hi), min(mid, hi)`, collapsing all three. Live M265 returns impact_low == impact_high == 4,355,020,000 (its whole 6-month realized GMV) with capped=true, broken=true, and confidence forced to "high" (insights.py:100). InsightCard.tsx:15 sees impact_high === impact_low, drops the interval, and renders one unhedged number. Score = 4.355e9 × CONF_W[high]/EFFORT_W[medium] = 2.90e9 — guaranteed rank 1.
- **Impact:** The least-reliable estimate in the system — a broken funnel where essentially none of the gap is recoverable — is displayed as a point figure equal to total sales and ranked above every well-evidenced card. Confidence-in-the-problem is being fed into a formula that means confidence-in-the-estimate.
- **Recommended fix:** For `broken` cards emit no rial impact (impact_low/high = 0, as the alert cards do) and rank them by a separate risk magnitude; keep confidence="high" as a problem flag only, not as CONF_W input.

### ZB-061 · Card trigger thresholds are fixed constants untethered from sampling error, with no multiple-comparison control

**Lens:** `statistics` · **Severity:** MEDIUM · **Effort:** medium

- **Where:** zarin/insights.py:66 (2pp), :187 (3pp), :218 (5pp), :247 (5pp), :274 (0.4), :334 (10pp); zarin/config.py:42
- **Observed:** MIN_SESSIONS_INSIGHT=100 admits a merchant into gap-card generation; at n=100 and p≈0.3 the SE of a rate is ~4.6pp, so the 2pp trigger sits well inside sampling noise. No standard error, z-test, chi-square or bootstrap exists anywhere in zarin/. `generate()` evaluates ~9 card conditions per merchant-period with no family-wise adjustment. The `_conf` label (insights.py:27-32) is a pure sample-size lookup that ignores peer dispersion entirely, even though p25/p75 are already computed in peers.benchmarks.
- **Impact:** At the low end of the allowed range the engine emits a confidently-worded, rial-denominated recommendation from a difference indistinguishable from noise, and the confidence chip cannot flag it because it is not derived from any variance. Uncertainty is asserted (three-level chip, scenario band) but never quantified from the data.
- **Recommended fix:** Gate emission on gap > k·SE(own rate) with SE = sqrt(p(1−p)/n) in addition to the fixed pp floor; scale the scenario band by observed peer dispersion (p25..p75) rather than the fixed [0.5, 0.75, 1.0]; state the multiple-comparison exposure in docs/ANALYTICS.md §7.

### ZB-062 · repeat_gap converts a share gap into incremental transactions — an identity error

**Lens:** `statistics` · **Severity:** MEDIUM · **Effort:** small

- **Where:** zarin/insights.py:238-265
- **Observed:** `extra_txns = (p50 − mine_share) * stats["cust_txns"]` where mine_share = repeat_txns/cust_txns. Peer median and own value are shares of the same total, so holding cust_txns fixed and raising the repeat share reallocates transactions from new to repeat customers rather than adding any. The result is priced at median_ticket and presented as «برآورد فروش بالقوه از رسیدن به میانه همتایان».
- **Impact:** The card's rial figure is not incremental revenue under any coherent counterfactual — it is the size of a mix shift priced as new sales. Confidence "low" and effort "hard" limit ranking damage, but the number itself estimates nothing.
- **Recommended fix:** Anchor the counterfactual on customers rather than transaction share: extra_txns = (peer repeat-txns-per-customer − own) × customers × ticket; or drop the rial figure and present it as a positioning gap with no monetary impact.

### ZB-063 · Unauthenticated free-text fields are persisted and rendered in the Control Center

**Lens:** `security` · **Severity:** MEDIUM · **Effort:** small

- **Where:** zarin/api.py:146-159 (`surface` param on /api/copilot and /api/copilot/feedback, `intent` on feedback) → zarin/ai/telemetry.py:23-34 → surfaced at telemetry.py:84
- **Observed:** `surface` and `intent` have no enum validation. Probes: `GET /api/copilot?m=M156&surface=EVIL` → 200, and `/api/admin/ai-ops` then shows `{"surface":"EVIL", ...}` in its `recent` list. `POST /api/copilot/feedback?intent=<img src=x onerror=alert(1)>&surface=INJECTED` → 200 and is appended to data/telemetry/ai_feedback.jsonl. Both endpoints are unauthenticated and unrate-limited.
- **Impact:** Any anonymous client can pollute the operator's AI-Ops dashboard and the durable JSONL audit trail with attacker-chosen labels, skewing the intent/feedback aggregates that the Control Center presents as ground truth, and growing the log without bound.
- **Recommended fix:** Validate with a Literal/Enum: `surface: Literal["merchant","ops"]` and constrain `intent` to the known plan intents (FastAPI returns 422 automatically); reject unknown values instead of recording them.

### ZB-064 · Unauthenticated endpoint proxies to an external LLM using the operator's API key, with no rate limit

**Lens:** `security` · **Severity:** MEDIUM · **Effort:** small

- **Where:** zarin/api.py:145-151 (/api/copilot) → zarin/ai/provider.py:57-80 (OpenRouter call with `Authorization: Bearer {self.api_key}`)
- **Observed:** No auth dependency on /api/copilot and no rate-limiting middleware anywhere (`app.middleware` at api.py:21 is telemetry only; grep for CORS/add_middleware returns no matches). With OPENROUTER_API_KEY set, each request spends the operator's quota; MAX_QUESTION_LEN=500 and AI_MAX_TOKENS=600 bound one call's size but not the call rate.
- **Impact:** Quota exhaustion / denial of the AI feature, and the operator's key is effectively lent to anonymous callers as a text-generation proxy. The free-model policy (zarin/ai/models.enforce_free) caps the dollar cost at $0, which is a real mitigation, but not the rate-limit one.
- **Recommended fix:** Put /api/copilot behind the same session gate as the merchant data, and add a simple per-IP token bucket in the existing obs middleware (a deque of timestamps is enough) before the provider is constructed.

### ZB-065 · Demo login gate claims an SMS was sent and is not disclosed as cosmetic in the UI

**Lens:** `security` · **Severity:** MEDIUM · **Effort:** small

- **Where:** frontend/src/pages/Login.tsx:83-95
- **Observed:** Step "otp" renders «کد ۵ رقمی پیامک‌شده به 0912 345 6789 را وارد کنید» and the form submits `onLogin(target)` unconditionally — any code, including none, logs in. The honest disclosure exists only in a source comment (Login.tsx:10-12) and README.md:144; nothing on screen tells a viewer no code was sent and nothing is verified.
- **Impact:** A demo or screenshot reads as a working phone/OTP authentication flow for a payments product. That misrepresents the security posture to a reviewer, and the same screen would be mistaken for real auth by anyone deploying it.
- **Recommended fix:** Add one line of muted text under the OTP boxes: «نسخه نمایشی — احراز هویت واقعی متصل نیست؛ هر کدی وارد شود ورود انجام می‌شود.» Costs nothing and makes the honest claim visible where the claim is made.

### ZB-066 · No application logging anywhere in the backend — nothing to diagnose an incident with

**Lens:** `reliability` · **Severity:** MEDIUM · **Effort:** small

- **Where:** zarin/ (whole package); zarin/__main__.py:26
- **Observed:** Scanned every zarin/**/*.py for `import logging`, `logger`, `traceback`, `exception_handler`: zero matches; only three `print()` calls in pipeline/__main__/eval. uvicorn runs with log_level="warning" so access logs are off; an ASGI traceback on stderr is the only trace of a 500, with no request id, no merchant/params context, and no persistence. Nothing correlates an ai_events.jsonl row to the HTTP request that produced it.
- **Impact:** When the Performance page does show a slow or failing endpoint, there is no artifact to go to next — no error log, no correlation id, no persisted trace. Post-hoc diagnosis of anything that happened before the terminal scrolled is impossible.
- **Recommended fix:** One `logging` config + a request-id generated in obs.middleware, echoed in a response header and stamped into both the obs event and the ai_events row; log exceptions at ERROR with that id.

### ZB-067 · Unknown /api/* paths return 200 text/html, masking contract drift and polluting telemetry

**Lens:** `reliability` · **Severity:** MEDIUM · **Effort:** small

- **Where:** zarin/api.py:267-276 (SPA catch-all) — verified live
- **Observed:** `curl -s -o /dev/null -w "%{http_code} %{content_type}" http://localhost:8630/api/doesnotexist` → `200 text/html`. The catch-all `@app.get("/{path:path}")` is not excluded for the /api prefix, so a mistyped or removed endpoint serves index.html. obs.middleware then records that path with status 200, counting it toward success and throughput.
- **Impact:** A frontend/backend version skew surfaces to the user as an opaque JSON parse error (api.ts:166 `res.json()` on HTML) instead of a 404, and the Control Center reports the broken path as 100% healthy. Silent failure with a plausible screen.
- **Recommended fix:** Return a JSON 404 for any unmatched path starting with `/api/` before falling through to index.html; add a test asserting /api/nope is 404 JSON.

### ZB-068 · Data-source «تازگی داده» reports the parquet build time, not the newest data

**Lens:** `reliability` · **Severity:** MEDIUM · **Effort:** small

- **Where:** zarin/sources/zarinpal.py:20 → Ops «منابع داده» card (OpsSources.tsx:46-50)
- **Observed:** `freshness = datetime.fromtimestamp(marts.stat().st_mtime)`. Live: /api/admin/sources reports freshness 2026-08-20 while /api/meta reports the data range ends 2026-06-30 — a ~7-week gap presented to the operator as data freshness. There is also no staleness threshold: `status` is 'ok' whenever the file merely exists.
- **Impact:** A pipeline that keeps running but stops ingesting (or ingests an empty delta) rewrites the file and the Control Center reports fresh, connected, ok — exactly the stale-data incident this view exists to catch. Same shape in GA4: status() returns connected/ok without ever calling the transport (ga4.py:54-58), though that path is unreachable today since fetch_fn is None.
- **Recommended fix:** Report `max(d)` from the sessions mart as freshness (build time can be a second field), and degrade status to a warning past a configured lag threshold.

### ZB-069 · No React error boundary — a render exception blanks the whole SPA

**Lens:** `reliability` · **Severity:** MEDIUM · **Effort:** small

- **Where:** frontend/src/App.tsx:160-175 (and main.tsx)
- **Observed:** Grep for ErrorBoundary/componentDidCatch/window.onerror/unhandledrejection across frontend/src: no matches. Pages index into fetched shapes directly (e.g. Overview.tsx:27 `ov.data.kpis`, OpsPerformance.tsx:22 `d.latency_ms!`, Copilot.tsx:113 `t.a!.answer_fa`), and TypeScript's non-null assertions are erased at runtime.
- **Impact:** Any unexpected payload shape or chart-library throw unmounts the entire tree to a white page with no message and no recovery path — worse than the per-page Empty states the code otherwise does well. No client-side error is reported anywhere either.
- **Recommended fix:** One error boundary around <main> rendering the existing <Empty> component plus a reload action; optionally POST caught errors to a telemetry endpoint so client failures reach AI-Ops-style visibility.

### ZB-070 · No response compression anywhere — 618 KB JS and 51 KB JSON served raw

**Lens:** `scalability` · **Severity:** MEDIUM · **Effort:** small

- **Where:** zarin/api.py:20 (app construction — no `GZipMiddleware`; grep for GZip/gzip across zarin/ returns 0 hits)
- **Observed:** `curl -H 'Accept-Encoding: gzip, br' /assets/index-Bx9Uu9tu.js` returns `content-length: 618105` with no `content-encoding`; `gzip -c` on the same file is 176,904 bytes (3.5x). `/api/meta` with `Accept-Encoding: gzip` returns 51,778 bytes uncompressed. Static mounts do send etag/last-modified, so repeat loads are 304s.
- **Impact:** ~440 KB of avoidable transfer on every cold load and ~44 KB on every `/api/meta` — significant on the Iranian mobile connections this Persian-first product targets, and it scales with every new user rather than being amortized.
- **Recommended fix:** `app.add_middleware(GZipMiddleware, minimum_size=1000)` — one line, already available in the installed Starlette. Optionally pre-compress the static assets at build time.

### ZB-071 · Single 618 KB bundle: no code splitting, merchant users download the whole Control Center

**Lens:** `scalability` · **Severity:** MEDIUM · **Effort:** medium

- **Where:** frontend/src/App.tsx / frontend/vite.config.ts — no `React.lazy`, `Suspense` or dynamic `import()` anywhere under frontend/src (grep returns 0 hits)
- **Observed:** `zarin/static/assets/` contains exactly one JS chunk, `index-Bx9Uu9tu.js` at 618,105 bytes, bundling react-dom, all of recharts, all 7 merchant pages and all 5 `ops/` pages. Alongside it are 9 Vazirmatn woff2 weights totalling 459 KB (all 9 `@font-face` rules are emitted by `vazirmatn/Vazirmatn-font-face.css`, imported unconditionally at theme.css:3).
- **Impact:** A merchant who never opens the Control Center still parses and executes its code; the environment is chosen *before* login, so the split is trivially available. Bundle parse/execute cost is the dominant first-paint term on mid-range mobile.
- **Recommended fix:** `const Ops = lazy(() => import('./ops/OpsApp'))` behind the pre-login environment choice, and split recharts into its own chunk via `build.rollupOptions.output.manualChunks`. Drop the unused Vazirmatn weights to the 3–4 the design actually uses.

### ZB-072 · Blocking 20s LLM call inside a sync endpoint can exhaust the shared threadpool

**Lens:** `scalability` · **Severity:** MEDIUM · **Effort:** medium

- **Where:** zarin/api.py:146 (`def ask(...)` — sync) → zarin/ai/gateway.py:91 → zarin/ai/provider.py:77 (`urllib.request.urlopen(req, timeout=self.timeout)`, `OPENROUTER_TIMEOUT` default 20s)
- **Observed:** Every route in api.py is a sync `def`, so all of them share the anyio threadpool (Starlette default 40 workers). The copilot path holds one of those workers for up to 20 s of blocking network I/O. `default_provider()` is called per request (gateway.py:68-69) and `urllib` opens a fresh TLS connection each time — no pooling, no keep-alive, and no cap on in-flight LLM calls.
- **Impact:** 40 concurrent slow/hanging copilot requests stall the entire API — including deterministic merchant endpoints that never touch the LLM. Because the analytics endpoints are also sync and lock-serialized, the failure mode is total, not partial.
- **Recommended fix:** Make `/api/copilot` `async def` and do the provider call with an async HTTP client (or `run_in_threadpool` with a dedicated bounded executor + `asyncio.Semaphore` cap), reuse one connection pool across calls, and lower the timeout well below the shared-threadpool budget.

### ZB-073 · Overview silently truncates the ranked feed to four cards with no way to see the rest

**Lens:** `product` · **Severity:** MEDIUM · **Effort:** small

- **Where:** frontend/src/pages/Overview.tsx:82
- **Observed:** `ins.data.cards.slice(0, 4)` is the only place InsightCard is rendered anywhere in the frontend (grep confirms). Live /api/insights?m=M250 returns 5 cards (inbank_gap, high_value_friction, no_attempt_gap, psp_friction, gmv_change); the fifth is unreachable in the UI. There is no "show all", no count, no indication that more exist.
- **Impact:** For any merchant with five or more findings, real recommendations — including the gmv_change alert, the only card that explains a sales swing — are invisible with no affordance suggesting they exist. The user cannot distinguish "four is all there is" from "four is all we showed you."
- **Recommended fix:** Render all cards, or keep four above the fold behind a "N فرصت دیگر" expander. One-line change plus a counter.

### ZB-074 · Time model contradicts the stated weekly job; the default landing has no period-over-period deltas at all

**Lens:** `product` · **Severity:** MEDIUM · **Effort:** small

- **Where:** frontend/src/ctx.tsx:43-61 (presets) and zarin/analytics.py via /api/overview
- **Observed:** PRODUCT.md:6 defines the product as "محصولی که پذیرنده هر هفته باز می‌کند" and the top chat prompt is "این هفته روی چه تمرکز کنم؟" (CopilotPage.tsx:8), but the only presets are all-6-months / 90d / 30d — no week, no custom range. The default preset is "all", which sets no cf/ct; live `curl /api/overview?m=M156` returns `previous: None`, so Overview's <Delta> (Overview.tsx:9) and the chat glance deltas all render nothing on first load.
- **Impact:** The default first screen of a "what changed" product shows five absolute numbers with zero change indicators. The weekly cadence the product claims is not expressible, and a merchant cannot ask the obvious "this month vs last month" or "vs the same week last year" question anywhere in the UI even though /api/changes already accepts arbitrary f1/t1/f2/t2 (api.py:135-142).
- **Recommended fix:** Add a 7-day preset and a custom range picker (native <input type="date">), default to 30d rather than all, and always send cf/ct so deltas are present on the landing.

### ZB-075 · Copilot covers seven regex intents, keeps no conversation memory, and answers unmatched questions with an unrelated KPI summary

**Lens:** `product` · **Severity:** MEDIUM · **Effort:** medium

- **Where:** zarin/copilot.py:39-131 (_plan); frontend/src/components/Copilot.tsx:56-67 (ask sends only the current question)
- **Observed:** Seven regex branches then a catch-all. Live probes: "آیا مشتریان موبایلی بیشتر شکست می‌خورند؟", "قیمت محصولاتم را افزایش بدهم؟", "بهترین شهر برای فروش من کجاست؟" and the follow-up "خب چرا؟" all return intent=fallback with the same generic GMV/conv/customers paragraph. `ask` posts only `q` — no turn history — so no follow-up can resolve against the previous answer. Live /api/admin/ai-ops shows fallback is the single most-used intent (29 of 91).
- **Impact:** On a chat-first landing, roughly a third of real questions get a confident-looking answer to a question the user did not ask. It never hallucinates numbers (the grounding discipline holds), but it also never says "I can't answer that" — the worst failure mode for trust in a chat surface, because a miss is indistinguishable from a hit.
- **Recommended fix:** Emit an explicit no-coverage response when no branch matches ("این را هنوز نمی‌توانم پاسخ دهم — می‌توانم درباره …") instead of falling through to the summary, and pass the previous turn's intent so pronoun follow-ups resolve.

### ZB-076 · No export, share, or digest anywhere in either surface

**Lens:** `product` · **Severity:** MEDIUM · **Effort:** medium

- **Where:** frontend/src/* (whole app); zarin/api.py (no report/export endpoint)
- **Observed:** Grep for CSV/download/print/email/share across frontend/src returns only the TypeScript `export` keyword and unrelated matters — no download link, no print stylesheet, no report endpoint, no scheduled digest, no notification. The evidence drawer shows up to 50 sample sessions (api.py:218) with no way to take them anywhere.
- **Impact:** A merchant who finds the 912 unverified payments cannot hand the list to their developer or accountant, and cannot be told about them without logging in. For a product positioned as a weekly habit, there is no mechanism that creates the weekly return — the merchant must remember on their own.
- **Recommended fix:** Ship CSV on the evidence drawer's session sample and a print-friendly Overview first; a weekly email/SMS digest of the top three cards is the highest-leverage retention feature and reuses copilot's "priorities" intent verbatim.

### ZB-077 · Merchant "کیفیت داده" page is dataset-global and ignores the merchant and period controls still shown above it

**Lens:** `product` · **Severity:** MEDIUM · **Effort:** small

- **Where:** frontend/src/pages/QualityPage.tsx:16 and zarin/api.py:237-238
- **Observed:** `get<Quality>("quality", {})` sends no merchant and no dates; `def quality():` takes no arguments. The page then shows platform-wide outcome mix and "۵ پذیرنده برتر {top5} از کل فروش موفق دیتاست را می‌سازند" (QualityPage.tsx:45) — a market-concentration statistic about other merchants — while the topbar still renders the merchant selector and the 6m/90d/30d segmented control (App.tsx:119-136), neither of which affects anything on the page.
- **Impact:** A merchant opening "data quality" under the "شفافیت" section reasonably expects the quality of their own data (their unknown-card share, their missing response codes, their coverage gaps) and instead gets platform statistics plus two controls that appear broken. It also surfaces cross-merchant aggregate information on a single-tenant surface.
- **Recommended fix:** Scope /api/quality by m and the selected window for the merchant surface, keep the methodology rules list as-is, and move the platform outcome mix and top-5 concentration to the Control Center where they belong; or hide the merchant/period controls on pages that ignore them.

### ZB-078 · Insight-to-action last mile is missing: the product cannot hand over the list it tells you to act on

**Lens:** `business` · **Severity:** MEDIUM · **Effort:** medium

- **Where:** zarin/api.py:216-232 (/api/evidence/sessions, `limit: int = Query(12, ge=1, le=50)`) vs insights.py:153 action «این پرداخت‌ها را از پیشخوان زرین‌پال تعیین تکلیف نمایید»
- **Observed:** Live call returns total=912 for M156 but at most 50 rows, ordered by amount. A repo-wide grep for download/CSV/export/webhook/SMS/email across frontend/src and zarin/*.py found no export, no scheduled digest, no notification channel, and no deep link into the ZarinPal panel.
- **Impact:** The merchant is told 61.8B IRR is sitting there and given no way to get the 912 identifiers, hand them to finance, or trigger anything. Value stays theoretical, and the "open it weekly" habit the product is designed around has no push channel to establish it.
- **Recommended fix:** Add a full CSV export for the sessions behind any card (session_key, date, amount, PSP, settled_at) and a deep link to the ZarinPal panel filtered to Paid status. A weekly SMS/email digest of the top card is the cheapest available retention lever.

### ZB-079 · "Payment Rescue" is a retrospective measurement sold as a capability

**Lens:** `business` · **Severity:** MEDIUM · **Effort:** small

- **Where:** README.md "The major innovations" table, row **Payment Rescue**; zarin/analytics.py funnel().recovery; insights.py:191-205 (recovery_gap card)
- **Observed:** The funnel reports recovery that already happened (M156: 691 of 21,818 first-fail sessions, 3.2%, 40.6B IRR — docs/screenshots/rd-funnel.png; platform-wide 39,658 sessions / 157.5B IRR via /api/admin/platform). The recovery_gap card's action is «دکمه پرداخت مجدد را نمایش دهید» — work the merchant must build in their own checkout. Nothing in the codebase retries, re-routes, or nudges a payer.
- **Impact:** Positioning it beside Paid-but-Unverified as a co-equal "major innovation" invites a PSP reviewer to discover the gap and discount the whole innovation list. It also gives away the strongest monetization play: retry-on-failure belongs in ZarinPal's own checkout, where the PSP captures the recovered volume rather than reporting on it.
- **Recommended fix:** Reframe Payment Rescue as measurement ("we quantify the rescue you already get and the gap to your peers"), and pitch native retry in ZarinPal checkout as the derived roadmap item — that is the version with a revenue-share story attached.

### ZB-080 · Control Center recommends a triage action it provides no way to perform, and half of it monitors Zarbin rather than ZarinPal

**Lens:** `business` · **Severity:** MEDIUM · **Effort:** medium

- **Where:** zarin/control.py:86 (platform insight action «پذیرندگان دارای بیشترین مبلغ تاییدنشده را … در اولویت بگذارید») and control.py:101-106 (performance/ai_ops = obs.summary / ai_telemetry.summary)
- **Observed:** The API route list in api.py contains no merchant-ranking or worklist endpoint; /api/admin/platform returns only aggregate KPIs, category bars and 2-3 static rule-based insight strings. /api/admin/performance returns Zarbin's own p50/p95 endpoint latency and /api/admin/ai-ops returns Zarbin's own token/cost telemetry (currently llm_requests=0). Meanwhile the concentration finding is available and unexploited: 53% of all platform paid_unverified value sits in one merchant (M156, 61.8B of 116.55B).
- **Impact:** For a PSP ops team the surface is thin: it tells them a problem exists platform-wide but not which of 343 merchants to phone, and two of four pages are product self-monitoring rather than payment operations. The highest-ROI internal use case — a ranked merchant call-list worth 116B IRR of stuck settlement — is one query away and absent.
- **Recommended fix:** Add /api/admin/merchants ranked by recoverable value (paid_unverified_amount, peer-gap opportunity, no-attempt severity) with the same evidence drawer, as the Control Center's landing view. It converts the internal surface from a status page into a revenue-recovery worklist and is the strongest argument for ZarinPal funding the product internally.

### ZB-081 · Speculative opportunity estimate is displayed in the same slot and weight as real money

**Lens:** `ux` · **Severity:** MEDIUM · **Effort:** small

- **Where:** frontend/src/components/InsightCard.tsx:32-39; visible in docs/screenshots/rd-overview.png (card 2)
- **Observed:** Card 1 shows «۶۱٫۸ میلیارد» — real settled-but-unverified money (impact_label_fa: «مبلغ واقعی در انتظار تعیین تکلیف (برآورد نیست)»). Card 2 shows «۱۴۷٫۳ میلیارد» in the identical .amount style — the midpoint of a 98.2–196.4 scenario range, carried by an «اطمینان پایین» chip and «مقایسه با ۵ همتا — نامطمئن». The disclaimer that separates them is rendered at var(--fs-xs) in --ink-3 and reads «برآورد فرصت (سناریوی محافظه‌کارانه تا خوش‌بینانه، نه بازه اطمینان آماری)» — the qualifier a merchant needs is written in the statistics vocabulary they do not have.
- **Impact:** The largest number on the merchant's home screen is a low-confidence guess that looks exactly like the one number on the page that is guaranteed real cash. A shop owner scanning for 10 seconds ranks the guess first.
- **Recommended fix:** Give estimate cards a visually distinct amount treatment (outlined/greyed with a «برآورد» prefix badge) reserved from the solid treatment used for actual money, and rewrite the label to «اگر به سطح همتایان برسید، حدوداً … بیشتر می‌فروشید — این یک تخمین است، نه پول موجود».

### ZB-082 · Customers page shows self-contradictory figures side by side

**Lens:** `ux` · **Severity:** MEDIUM · **Effort:** small

- **Where:** frontend/src/pages/CustomersPage.tsx:32-51; docs/screenshots/rd-customers.png
- **Observed:** Live /api/customers?m=M156 returns customers=23801, new_customers=23801, repeat_customers=4228. The UI therefore renders «مشتریان این دوره ۲۳,۸۰۱ / ۲۳,۸۰۱ مشتری جدید» immediately beside «سهم تراکنش مشتریان تکراری ۳۵٫۸٪ / ۱۷٫۸٪ از مشتریان». Everyone is new and 17.8% are returning, on the same row.
- **Impact:** A merchant reading two adjacent tiles gets a flat contradiction with no reconciliation. The cause (the selected window is the entire dataset, so first-purchase == in-period for everyone) is invisible in the UI, so the natural conclusion is that the numbers are wrong — which poisons trust in the rest of the page.
- **Recommended fix:** Suppress or annotate the «مشتری جدید» sub-line when new_customers === customers, e.g. «همه مشتریان در این بازه اولین خریدشان را داشتند چون بازه انتخابی کل تاریخچه است».

### ZB-083 · Data-fetch failures show raw English exception text and offer no retry

**Lens:** `ux` · **Severity:** MEDIUM · **Effort:** small

- **Where:** frontend/src/ctx.tsx:90 and :110 (`error: String(e)`), rendered at Overview.tsx:26, FunnelPage.tsx:19, CustomersPage.tsx:11, PeersPage.tsx:18, ChangesPage.tsx:45, QualityPage.tsx:17
- **Observed:** api.ts:165 throws `new Error("overview: 500")`; ctx stores String(e) and the pages pass it straight into <Empty body={...}>, so the merchant sees «خطا در دریافت داده / Error: overview: 500» in an otherwise fully Persian RTL UI. None of these six error branches renders a retry control — the only retry in the app is inside the evidence sample loader (EvidenceDrawer.tsx:117).
- **Impact:** On any backend hiccup the merchant is dead-ended with an English stack-ish string and must know to reload the browser. This is the single most likely first-run failure a non-technical user will meet.
- **Recommended fix:** Map the error to one Persian sentence («ارتباط با سرور برقرار نشد») and add a «تلاش دوباره» button that re-runs the fetch; keep the raw string behind the console or a small «جزئیات فنی» disclosure.

### ZB-084 · The signature «این عدد از کجا آمد؟» drawer is written for an analyst, not a merchant

**Lens:** `ux` · **Severity:** MEDIUM · **Effort:** medium

- **Where:** frontend/src/components/EvidenceDrawer.tsx:83-106; docs/screenshots/desk-evidence.png
- **Observed:** The drawer's body order is متریک → فرمول (LTR monospace, e.g. `count(sessions where outcome = paid_unverified)`) → پارامترها (raw keys m/f/t) → «کوئری اجراشده» with a full SELECT statement. Line 90 renders computed_at as the raw ISO string «2026-08-20T05:19:00+00:00» — Gregorian and un-localised, while every other date in the app goes through faDate/Jalali. The definition text itself carries English identifiers («settled_at ثبت شده»، «هرگز Verify نکرده»).
- **Impact:** The affordance meant to make every number traceable in language a merchant understands is dominated by SQL and English column names. A shop owner opens it once, sees code, and stops using the feature that carries the product's trust story.
- **Recommended fix:** Lead the drawer with a one-paragraph «به زبان ساده» restatement and the sample-session table, and collapse فرمول/پارامترها/کوئری behind a «جزئیات فنی» toggle. Run computed_at through faDate.

### ZB-085 · Rial-only amounts with no Toman equivalent and no on-screen currency note

**Lens:** `ux` · **Severity:** MEDIUM · **Effort:** small

- **Where:** frontend/src/fmt.ts:11-21 (rial); Overview.tsx:45,60; meta.notes.currency is fetched but rendered nowhere on merchant pages
- **Observed:** Every amount renders as e.g. «۱٫۹۵ هزار میلیارد ریال» / «۴۱٫۴ میلیون ریال». /api/meta returns notes.currency = «همه مبالغ به ریال است.», but grep shows meta.notes is only consumed for notes.customer (CustomersPage.tsx:25) — the currency note never appears on Overview, Funnel or Changes. There is no Toman toggle anywhere in the codebase.
- **Impact:** Iranian shop owners transact and think in تومان. «هزار میلیارد ریال» is the hardest available format for the target user to hold in their head, and a factor-of-ten misread of the headline sales figure is the likely failure mode. Nothing on screen even states the unit convention.
- **Recommended fix:** Add a ریال/تومان toggle in the topbar next to the period segment (a one-line divide-by-10 in fmt.rial), persisted in sessionStorage; default to تومان for the merchant workspace and keep ریال for Ops.

### ZB-086 · Waterfall zero-axis divider references an undefined CSS variable and renders invisible

**Lens:** `design` · **Severity:** MEDIUM · **Effort:** small

- **Where:** frontend/src/components/charts.tsx:116 (Waterfall); «سهم هر عامل در تغییر فروش» on the what-changed page
- **Observed:** `background: "var(--line-strong)"` — grepping frontend/src for `line-strong` returns exactly this one hit; theme.css defines only --line, --line-2, --line-3. With no fallback the 1px div paints transparent. docs/screenshots/desk-changes.png shows the three bars floating around an unmarked centre with no visible axis.
- **Impact:** A waterfall's whole readability depends on the ±0 reference line: without it the reader cannot tell where positive stops and negative starts, and the −۴۷٫۸ میلیارد conversion bar loses its anchor. The chart still reads by colour, but the geometry is unmoored.
- **Recommended fix:** Change to `var(--line-3)`. Longer term, add a build-time check (or a CSS-var lint) for `var(--x)` names not defined in theme.css — this is the only such leak but it shipped silently.

### ZB-087 · Latin digits leak into a Persian-first UI in three places, while the Persian-digit helper sits unused

**Lens:** `design` · **Severity:** MEDIUM · **Effort:** small

- **Where:** frontend/src/components/charts.tsx:71 and :138; frontend/src/components/EvidenceDrawer.tsx:90, :99; frontend/src/fmt.ts:57
- **Observed:** HourHeat renders `{h}` (0…23) and its title attribute `ساعت ${h}` as raw JS numbers; CohortGrid renders headers as `+${k}` → "+1 +2 +3 +4 +5", plainly Latin in rd-customers.png next to Persian cell values (۱۱٪) and Persian row labels (دی ۰۴). EvidenceDrawer prints `ev.computed_at` raw — desk-evidence.png shows «زمان محاسبه  2026-08-20T05:19:00+00:00» directly beneath a correctly Jalali-rendered «دوره  ۱۱ دی ۱۴۰۴ تا ۹ تیر ۱۴۰۵» — and param values raw (f 2026-01-01). fmt.ts:57 exports HOURS_FA, a ready-made Persian 0–23 array, which no file imports.
- **Impact:** Inconsistent digit systems inside the same grid and the same definition list. The evidence drawer is the product's transparency centrepiece, and it is where the Persian localisation visibly stops — a Gregorian UTC ISO timestamp under a Persian label is the most jarring instance.
- **Recommended fix:** Use the existing HOURS_FA for hour labels, `+${faNum(k)}` for cohort headers, and faDate()/an Intl fa-IR dateTime format for computed_at (keep the ISO string in a title attribute for copy/debug). Same for date-valued params.

### ZB-088 · Backend and frontend ship two different Persian thousands separators, both visible on one page

**Lens:** `design` · **Severity:** MEDIUM · **Effort:** small

- **Where:** zarin/fa.py:4 vs frontend/src/fmt.ts:2; both rendered on the Ops Overview screen
- **Observed:** fa.py:4 is `str.maketrans("0123456789,.", "۰۱۲۳۴۵۶۷۸۹،٫")` — it maps the group separator to U+060C ARABIC COMMA. Live probe of /api/admin/platform returns body_fa "۸،۷۰۶ پرداخت در بانک تسویه شده". A node probe of the frontend's `new Intl.NumberFormat('fa-IR').format(23801)` returns "۲۳٬۸۰۱" — U+066C ARABIC THOUSANDS SEPARATOR. OpsOverview.tsx renders KPI numbers with the frontend formatter (U+066C) and insight `body_fa` verbatim (U+060C) inside the same card stack.
- **Impact:** Two visually different glyphs for the same function within one viewport. U+060C is a sentence comma, not a digit-group separator; using it inside numerals is typographically wrong in Persian and breaks the tabular-nums rhythm the .num class establishes.
- **Recommended fix:** Change fa.py's translation table to map "," → "٬" (U+066C) so server-rendered Persian numerals match the client, and add one assertion in tests/ pinning the separator codepoint.

### ZB-089 · Merchant and Operations surfaces are visually indistinguishable; the differentiation hook is dead code

**Lens:** `design` · **Severity:** MEDIUM · **Effort:** medium

- **Where:** frontend/src/App.tsx:78 (`data-workspace={ws}`) vs frontend/src/theme.css — no rule matches it anywhere; compare docs/screenshots/rd-overview.png with rd-ops.png
- **Observed:** grep for `data-workspace` in theme.css returns zero matches. Side by side, the two surfaces share the same --bg, same 248px sidebar, same --brand-soft yellow active pill with the same inset bar, same --r-l card radius, same --shadow-1, same type scale, same topbar segmented control. The only ops-specific styling is padding: .ops-panel/.ops-card at 14/16px vs .card content at 18–20px — a density delta invisible without an A/B comparison.
- **Impact:** The product's stated model — a calm merchant surface vs a denser internal control centre — is not expressed visually. Nothing on screen signals "you are in an internal tool", which for an internal ops surface is both an orientation and a safety cue, and it costs the design its most legible strategic idea.
- **Recommended fix:** Use the existing data-workspace attribute: under [data-workspace="ops"] shift the accent from --brand to --blue-2 for the active nav and rank badges, drop --bg a step cooler, tighten --fs and section margin-block, and reduce card radius one notch. That is a ~15-line token override, not a second design system.

### ZB-090 · No skip link past the repeated sidebar; no h1 on five of seven merchant pages

**Lens:** `accessibility` · **Severity:** MEDIUM · **Effort:** small

- **Where:** frontend/src/App.tsx:80-108 (`aside.sidebar` + `nav.side-nav`) and App.tsx:142 (`<main className="main" id="main">`); pages FunnelPage.tsx, PeersPage.tsx, CustomersPage.tsx, ChangesPage.tsx, QualityPage.tsx
- **Observed:** `main` carries `id="main"` but nothing in App.tsx or index.html renders an anchor to it — I grepped the whole `frontend/src` tree for a skip/bypass link and found none. The 7-item sidebar nav plus topbar controls are re-rendered on every route. Separately, only Overview.tsx:34 and the ops pages render an `<h1>`; Funnel/Peers/Customers/Changes/Quality begin at `<h2>` via `ui.tsx:38-46 Section`, and CopilotPage's `<h1>` (Copilot.tsx:80) exists only while `turns.length === 0` and disappears once the user asks anything. The page name shown in the topbar (App.tsx:115 `.t-title`) is a plain `<div>`, so it is not in the heading tree at all.
- **Impact:** Fails WCAG 2.1 A 2.4.1 Bypass Blocks — a keyboard or switch user must traverse the sidebar, merchant `<select>` and four period buttons before reaching content on every navigation. The missing/vanishing `h1` breaks the standard screen-reader "jump to h1" orientation move and leaves five pages with no top-level heading (1.3.1 / 2.4.6).
- **Recommended fix:** Add a visually-hidden-until-focused `<a href="#main">پرش به محتوا</a>` as the first child of `.app`, and promote App.tsx:115 `.t-title` to `<h1>` (dropping the per-page `h1` on Overview/ops to `h2`) so every route has exactly one, stable, top-level heading.

### ZB-091 · Rich tooltips are not hoverable or dismissible, and their content is unlikely to reach a screen reader

**Lens:** `accessibility` · **Severity:** MEDIUM · **Effort:** medium

- **Where:** frontend/src/components/Tooltip.tsx:56-77 (`Term`); CSS `.tip-pop { pointer-events: none }` theme.css:372; `.term > .lbl` theme.css:368
- **Observed:** The popup sets `pointer-events:none`, so a user who magnifies the page cannot move the pointer onto the tooltip to read it. `Escape` is bound only via `onKeyDown` on the trigger span (Tooltip.tsx:62), so a mouse/hover user has no way to dismiss the overlay without moving the pointer. The trigger is a `<span role="button" tabIndex={0}>` with no Enter/Space handler — `onClick` on a span does not fire from the keyboard — and `aria-describedby={box ? popId : undefined}` is applied only *after* `onFocus` sets state, so the description does not exist at the moment focus is computed and will typically not be announced. `aria-label={`توضیح: ${rich?.title}`}` also replaces the visible term text as the accessible name. The dashed affordance `border-bottom: 1px dashed var(--line-3)` is #d8d9de on white = 1.41:1, effectively invisible.
- **Impact:** Fails WCAG 2.1 AA 1.4.13 Content on Hover or Focus (not hoverable, not dismissible) and A 2.5.3 Label in Name (the name "توضیح: …" does not contain the visible label). The three-part plain-language explanations — the mechanism that makes the product understandable to non-analysts — are in practice unavailable to screen-reader users and to magnifier users.
- **Recommended fix:** Drop `pointer-events:none` and keep the tooltip open on tooltip hover; bind Escape on `document` while open; render the tooltip text in a persistent visually-hidden `<span id={popId}>` so `aria-describedby` is stable and always resolvable; use a real `<button>` with `aria-describedby` and keep the visible label inside it (move "توضیح" into visually-hidden text). Darken the dashed underline to ≥3:1.

### ZB-092 · Charts and the hour heatmap expose no data to assistive technology

**Lens:** `accessibility` · **Severity:** MEDIUM · **Effort:** medium

- **Where:** frontend/src/components/charts.tsx:10 (`TrendChart` `role="img" aria-label="روند روزانه فروش موفق"`), :62-74 (`HourHeat`), :44 and :110 (`role="cell" aria-hidden` inside `role="table"`)
- **Observed:** `TrendChart` wraps the entire Recharts SVG in `role="img"` with a label that names the chart but conveys none of its values, and there is no adjacent table or summary. `HourHeat` puts all 24 hours' data in `title` attributes (charts.tsx:68) *inside* a `role="img"` container, so the values are both hidden from AT by the img role and unreachable by keyboard (`title` requires hover). In `FunnelViz` and `Waterfall` the bar `<div role="cell" aria-hidden>` sits inside `role="row"` within `role="table"`, so rows advertise a cell count that AT is then told to ignore — an invalid ARIA table structure. `CohortGrid` (charts.tsx:127-177) is a CSS grid of plain `<div>`s with no table or grid roles at all, so row/column relationships are lost entirely.
- **Impact:** Fails WCAG 2.1 A 1.1.1 Non-text Content (the text alternative does not convey equivalent information) and 1.3.1 Info and Relationships for the cohort grid and the malformed ARIA tables. A blind merchant can read the KPI numbers but cannot obtain the daily trend, the hourly distribution, or any cohort retention value — the analysis the product exists to deliver.
- **Recommended fix:** Give each chart a visually-hidden data table (or a `<details>` "مشاهده به صورت جدول") generated from the same array; replace the ARIA-table `div`s in FunnelViz/Waterfall with real `<table>` markup (the codebase already uses `.tbl` correctly elsewhere) and drop the `aria-hidden` cells; render CohortGrid as a `<table>` with `<th scope="row">` month headers.

### ZB-093 · Copilot answers are announced unreliably; pending state and route changes are silent

**Lens:** `accessibility` · **Severity:** MEDIUM · **Effort:** medium

- **Where:** frontend/src/components/Copilot.tsx:112 (`<div className="bubble bubble-a num" aria-live="polite">`), :110 (pending bubble), :61/66 (`scrollIntoView`); frontend/src/App.tsx:50-59 (`useRoute`)
- **Observed:** The `aria-live="polite"` attribute is on the answer bubble itself, which is created in the same render as its content. Live regions must be present in the DOM before content is injected to be reliably announced by NVDA/JAWS/VoiceOver; a newly inserted node carrying `aria-live` is generally not announced. The pending bubble "در حال محاسبه از داده‌های شما" (Copilot.tsx:110) has no live region and no `aria-busy`, so there is no perceivable feedback at all during the request. On route change, `useRoute` only calls `window.scrollTo(0,0)` — focus stays on the sidebar button and nothing announces that the page content changed. The login flow (Login.tsx:22 `choose`) swaps the entire card with no focus move, dropping focus to `<body>`.
- **Impact:** Fails WCAG 2.1 AA 4.1.3 Status Messages for the assistant's answers and its loading state, and A 2.4.3 Focus Order at the login step transition. A screen-reader user asks a question and hears nothing — neither that work is in progress nor that an answer arrived — and must hunt for it manually.
- **Recommended fix:** Render one persistent `<div aria-live="polite" aria-atomic="false">` wrapper around `.chat` at mount and let bubbles appear inside it; set `aria-busy` on that wrapper while pending. On route change, move focus to the `<main>` (`tabIndex={-1}`) and announce the new page title in a persistent live region. In `Login.choose`, focus the phone `<input>` after the step transition.

### ZB-094 · OTP entry is hostile to paste, autofill and motor impairment; input borders fail non-text contrast

**Lens:** `accessibility` · **Severity:** MEDIUM · **Effort:** medium

- **Where:** frontend/src/pages/Login.tsx:87-93 (five `.otp-box` inputs) and :77 (phone input); theme.css:156-166 (`.field`, `.otp-box` border `#e0e0e5`), :324 (`.composer form` border)
- **Observed:** The five OTP boxes have `maxLength={1}` and a `setDigit` handler that takes `v.replace(/\D/g,"").slice(-1)` — pasting or SMS-autofilling a five-digit code puts one digit in one box and discards the rest. There is no `autoComplete="one-time-code"` on any box, no `type="tel"` on the phone field (only `inputMode`), no grouping element with an accessible name around the five boxes (only per-box `aria-label={`رقم ${i+1}`}`), and no `aria-describedby` linking them to the "کد ۵ رقمی پیامک‌شده به …" instruction at Login.tsx:84. Border colours: `#e0e0e5` on `--surface` #fff = 1.32:1 and `--line` #e7e7ea = 1.23:1 — the only thing that identifies a field or the `.seg` period control as an interactive component.
- **Impact:** Fails WCAG 2.1 AA 1.4.11 Non-text Contrast (UI component boundaries need ≥3:1) and A 1.3.5 Identify Input Purpose (no `autocomplete` on the phone/OTP fields). The split-box OTP with no paste distribution is a well-known barrier for users with motor impairments, dyslexia and screen-magnifier users, and it is the mandatory gate to the entire product.
- **Recommended fix:** Add `autoComplete="one-time-code"` and an `onPaste` handler that distributes digits across the boxes (or replace the five boxes with one `<input inputMode="numeric" autoComplete="one-time-code" maxLength={5}>`); wrap them in a `<fieldset>` with a `<legend>` and point `aria-describedby` at the instruction paragraph; add `autoComplete="tel"` to the phone field; darken `--line`/field borders to ≥3:1 against their background.

### ZB-095 · Eval harness never exercises the grounding guard; grounding_quality is tautological

**Lens:** `ai-grounding` · **Severity:** MEDIUM · **Effort:** medium

- **Where:** zarin/ai/eval/runner.py:18 (use_llm=False) and :48 (grounding_quality = len(evidence) >= 1)
- **Observed:** Every case runs deterministic-only, so no LLM output is ever scored. grounding_ok is just evidence_count>=1, and every branch of copilot._plan() appends at least one evidence dict before returning — the check cannot fail, hence the fixed 100%. The guard's only adversarial coverage is 7 numeric assertions in tests/test_ai.py:123-135.
- **Impact:** The harness measures regex intent routing, not AI quality, while README.md:46 and OpsAI.tsx:65-76 present it as the product's AI quality evaluation. Guard regressions of the kind above would go uncaught.
- **Recommended fix:** Add a stubbed-provider adversarial track (fabricated number, rescaled number, unit swap, metric swap, pure-prose causality, empty, English) asserting accept/reject, and report guard precision/recall separately from routing accuracy.

### ZB-096 · No out-of-scope branch: 41% of live questions fall through to a generic sales summary

**Lens:** `ai-grounding` · **Severity:** MEDIUM · **Effort:** medium

- **Where:** zarin/copilot.py:124-131 (terminal fallback branch)
- **Observed:** Live /api/admin/ai-ops intent histogram: fallback 53 of 130 events, the largest bucket. Verified fall-throughs include «نرخ تبدیل من چند است؟» (a metric the engine holds), «how is my conversion rate?», «سلام», and a prompt-injection string — all answered with the same GMV/conversion/customer summary at confidence=medium.
- **Impact:** Users asking a supported question in unmatched wording get a non-answer presented with medium confidence and traceable evidence, which reads as if the question was understood. Routing is 7 hand-written Persian regexes with no normalization or synonym layer.
- **Recommended fix:** Split the terminal branch into overview (question maps to headline KPIs) and out_of_scope (confidence=low, explicit capability list); add ZWNJ/ی-ك normalization and a small synonym table so «نرخ تبدیل» routes to the funnel branch.

### ZB-097 · Empty or non-Persian LLM output is accepted and displayed

**Lens:** `ai-grounding` · **Severity:** MEDIUM · **Effort:** small

- **Where:** zarin/ai/gateway.py:99-119 (no non-empty / language check before constructing the LLM AIResponse)
- **Observed:** Fake provider returning "" produced source=llm, grounded=True, answer_fa='' (blank chat bubble); returning "Sales fine." produced source=llm with English text, despite system-prompt rule ۴ «پاسخ فقط فارسی باشد». is_grounded returns True for both because neither contains digit runs.
- **Impact:** A truncated (AI_MAX_TOKENS=600), rate-limited or misbehaving free model can render an empty or English answer in an RTL Persian merchant UI, with no fallback to the correct deterministic text and no telemetry flag.
- **Recommended fix:** Before accepting, require comp.text.strip() non-empty and a minimum Persian-letter ratio (e.g. >0.5 of letters in the Arabic block); otherwise fall back with a bad_output quality flag.

### ZB-098 · Five endpoints have no HTTP-level happy-path test; the admin guard is spot-checked on one route only

**Lens:** `testing-qa` · **Severity:** MEDIUM · **Effort:** small

- **Where:** zarin/api.py:107-111 (/api/insights), 121-125 (/api/customers), 128-132 (/api/peers), 135-142 (/api/changes success), 237-247 (/api/quality); tests/test_control.py:88-93
- **Observed:** Coverage misses api.py:109-111, 123-125, 130-132, 141-142, 239-247 — i.e. those route bodies never execute. The underlying analytics functions are called directly in test_metrics.py, so the HTTP wiring (`_check_merchant`, `_dates`, `_valid_date` normalization) on those five routes is unverified; /api/changes is only reached via its 400 path. For auth, test_admin_guard_enforced_when_token_set asserts 401/200/401 on `/api/admin/performance` alone, relying on all eight admin routes sharing `dependencies=_ADMIN` (api.py:165) by convention rather than by assertion.
- **Impact:** Dropping `_check_merchant` from /api/customers, or omitting `dependencies=_ADMIN` from a newly added /api/admin/* route, would leak data or bypass the operator token with the suite green.
- **Recommended fix:** Add a parametrized test iterating `app.routes` that asserts (a) every merchant-scoped route returns 404 for an unknown `m` and 400 for a bad date, and (b) every path starting with `/api/admin` returns 401 when ADMIN_TOKEN is set and no header is sent.

### ZB-099 · The path-traversal test can pass vacuously — silent `return` instead of skip, and an empty body satisfies every assertion

**Lens:** `testing-qa` · **Severity:** MEDIUM · **Effort:** small

- **Where:** tests/test_api.py:75-89
- **Observed:** `if not (STATIC_DIR / 'index.html').exists(): return` — a bare return, so on a checkout without a built SPA the repo's most security-relevant test reports PASS rather than SKIP. (Here `zarin/static/index.html` does exist, so it currently runs.) The final assertion also accepts `content == b''`, meaning a route regression that returns an empty 200 body passes all four checks.
- **Impact:** The traversal/UNC guard is protected by a test whose green status does not distinguish 'guard verified' from 'guard not exercised' — precisely the case in any environment where the frontend has not been built.
- **Recommended fix:** Use `pytest.skip('SPA not built')` so the gap is visible, drop the `content == b''` escape hatch, and add a positive control asserting a legitimate asset path is still served.

### ZB-100 · No coverage or mutation gate; OpenRouter transport and telemetry restart-recovery are untested

**Lens:** `testing-qa` · **Severity:** MEDIUM · **Effort:** medium

- **Where:** pyproject.toml:15-19 (dev deps: pytest, httpx, ruff only); zarin/ai/provider.py:49-87, 101-104; zarin/store.py:29-42
- **Observed:** No pytest-cov, no coverage threshold, no mutation testing configured — coverage had to be measured with an ad-hoc `--with coverage` run. provider.py is 52% covered: the HTTP request build, response parsing, timeout and error handling in the real OpenRouter path (49-87) and `default_provider()` (101-104) never execute; conftest.py:14-15 claims 'the key-present and transport paths are covered via explicit injection' but injection only exercises the FakeProvider/BoomProvider protocol, not this code. store.py:32-42 (reload of persisted JSONL telemetry on startup, including the JSONDecodeError skip) is also unexercised, so restart recovery of the AI-ops cost/telemetry data is unverified.
- **Impact:** Coverage can regress silently with no gate. A malformed OpenRouter payload is contained only by gateway.py's blanket `except Exception` (which degrades every LLM answer to fallback rather than surfacing the bug), and a corrupt telemetry file's effect on the Ops AI page is unknown.
- **Recommended fix:** Add pytest-cov with a per-module floor (e.g. fail under 80% on zarin/, 60% on the weakest modules), and add tests for provider.py with a stub `fetch_fn`/urlopen covering 200-with-unexpected-shape, non-200, and timeout; add a store.py round-trip test that writes a JSONL file with one corrupt line and asserts recovery.

## LOW severity

### ZB-101 · 2,777 lines of strict TypeScript with no test at all

**Lens:** `rubric-official` · **Severity:** LOW · **Effort:** small

- **Where:** frontend/src/ (25 files); tests/ contains only Python (tests/test_api.py, test_metrics.py, test_insights_peers.py, test_ai.py, test_control.py, test_sources.py)
- **Observed:** The backend has 56 targeted tests covering grain, LMDI exactness and the grounding guard's digit-substring attacks. The frontend has none — including ChangesPage.tsx:22-32, which re-derives the period midpoint in JS and must stay byte-identical to zarin/insights._change_alert:380 for the page and the insight card to quote the same split (the code comment says so explicitly, nothing enforces it).
- **Impact:** A silent divergence between the JS midpoint and the Python midpoint would make the What-Changed page and the GMV-change card disagree with no test failing.
- **Recommended fix:** Either move the midpoint to the API (return the split the backend used and have the page consume it), or add one vitest asserting the JS midpoint matches a fixture generated from the Python function. The former is smaller and removes the duplication entirely.

### ZB-102 · Two parallel copilot planners with divergent internal contracts

**Lens:** `architecture` · **Severity:** LOW · **Effort:** small

- **Where:** zarin/copilot.py:39 (_plan → _Plan) vs zarin/ops_copilot.py:32 (_plan → 4-tuple)
- **Observed:** Both implement the identical pattern (regex intent chain → deterministic Persian text + refs + confidence → gateway.explain) but one returns a `_Plan` class with __slots__ and the other an unnamed 4-tuple. Both are linear if/regex chains with order dependencies that already required a comment to defend (copilot.py:72-73: recovery must be matched before friction).
- **Impact:** Intent routing is the most likely growth axis for a chat-first product, and each new intent is another regex inserted at the right position in a chain with no test that the ordering is stable. The two surfaces will drift because nothing forces them to share a shape.
- **Recommended fix:** Share the `_Plan` type between both planners, and move each intent to a `(pattern, handler)` table so ordering is data rather than control flow — the eval harness in zarin/ai/eval already asserts intent per case and would catch regressions.

### ZB-103 · Quality gates are thin on the frontend and permissive on the backend

**Lens:** `architecture` · **Severity:** LOW · **Effort:** small

- **Where:** frontend/package.json (no lint deps), [tool.ruff] in pyproject.toml
- **Observed:** No eslint config or dependency exists anywhere in frontend/, yet frontend/src/ctx.tsx:92,112 and EvidenceDrawer.tsx:23 carry `// eslint-disable-next-line react-hooks/exhaustive-deps` directives that nothing enforces. Zero frontend tests (no *.test.* files). `[tool.ruff]` sets only line-length and target-version, so `ruff check` runs the default E4/E7/E9/F subset — no import sorting, bugbear, or upgrade rules. No Python type checker despite TS being strict. Residue this misses: a no-op ternary at Overview.tsx:14 (`${good ? "" : ""}`) and dead arithmetic at peers.py:90 (`- me["first_try_ok"] - 0`).
- **Impact:** 2,777 lines of TypeScript — including all state management and the hand-mirrored API types — have exactly one gate (`tsc --noEmit`), and the exhaustive-deps suppressions are load-bearing for correctness of the fetch hooks but unverified.
- **Recommended fix:** Add eslint + react-hooks plugin to the frontend (the disable comments are already written for it) and expand ruff's select to at least I, B, UP. Both are config-only changes.

### ZB-104 · Assorted dead code and leftover expressions that no configured gate catches

**Lens:** `code-quality` · **Severity:** LOW · **Effort:** small

- **Where:** frontend/src/pages/Overview.tsx:14, frontend/src/components/ui.tsx:15-16, frontend/src/fmt.ts:57, zarin/peers.py:90, zarin/registry.py:26-77
- **Observed:** `Overview.tsx:14` — `className={\`d num ${good ? "" : ""}\`}`, a ternary with two empty branches. `IconMore` (ui.tsx:15), `IconSearch` (ui.tsx:16) and `HOURS_FA` (fmt.ts:57) each have exactly one occurrence in `frontend/src` — their own definition. `peers.py:90` — `fp = me["attempted"] - me["first_try_ok"] - 0`. Eight of the 22 `Metric(...)` entries (`sessions`, `verified`, `attempt_rate`, `failed_bank_rate`, `recovered`, `repeat_customer_share`, `repeat_gmv_share`, `fee_index`) are never passed to `evidence()` anywhere and no endpoint exposes the registry wholesale.
- **Impact:** Small individually, but `noUnusedLocals` cannot see unused *exports* and ruff's default rule set cannot see unused registry entries, so this class of rot accumulates unchecked.
- **Recommended fix:** Delete the four dead frontend/Python expressions; either surface the registry via a `/api/metrics` endpoint (which would also make the 8 orphan definitions useful) or drop them.

### ZB-105 · Convention inconsistencies a new engineer must absorb before extending either copilot

**Lens:** `code-quality` · **Severity:** LOW · **Effort:** small

- **Where:** zarin/ops_copilot.py:32 vs zarin/copilot.py:32-37; zarin/peers.py:36,40,44; zarin/analytics.py:17 / insights.py:23 / peers.py:132; zarin/insights.py:320,370,376 and analytics.py:215
- **Observed:** `copilot._plan` returns a `_Plan` class with `__slots__`; the sibling `ops_copilot._plan` returns a bare 4-tuple `(text, intent, refs, conf)` for the identical concept. `peers.py:36,40,44` build peer SQL via `POOL_SQL.split('WHERE')[1]` — string surgery on a query to reuse its predicate, which breaks silently if `POOL_SQL` ever gains a second `WHERE`. The `f"{f} تا {t}"` period formatter exists three times as `_period` (analytics.py:17), `_fmt_period` (insights.py:23) and `_p` (peers.py:132). Function-body imports appear in four places (`insights.py:320,370,376`, `analytics.py:215`) where only `peers.py:87` has a genuine cycle to avoid. `insights.py:369` names a module-level helper `__peer_repeat` with a double underscore.
- **Impact:** None of these are bugs, but together they mean there is no single answer to «how do we do X here» for planners, SQL reuse, imports, or naming — the friction lands on the next contributor rather than the current one.
- **Recommended fix:** Give `ops_copilot` the same `_Plan` return type, replace the `split('WHERE')` trick with a named `_POOL_PREDICATE` constant, keep one period formatter in `fa.py`, and lift the non-cyclic local imports to module scope.

### ZB-106 · Overview's verified-count KPI opens the GMV metric's evidence drawer

**Lens:** `data-correctness` · **Severity:** LOW · **Effort:** small

- **Where:** frontend/src/pages/Overview.tsx:49 (KPI «پرداخت موفق»)
- **Observed:** The tile displays `faNum(k.verified)` — a count of Verified sessions — but passes `ov.data.evidence.gmv` to EvBtn. The drawer therefore shows name «فروش موفق (GMV)», formula `sum(amount | outcome = verified)` and the caveat «مبالغ به ریال است.» for a number that is not an amount. A correct Metric("verified") exists at registry.py:29-30 and is never used anywhere.
- **Impact:** A user auditing the count is shown the definition and formula of a different metric, in a product whose header text (Overview.tsx:38) promises every number on the page is traceable to raw data.
- **Recommended fix:** Add a `verified` entry to analytics.overview()'s evidence dict using the existing Metric("verified") and point the tile at it.

### ZB-107 · Same concentration statistic suppressed at two different sample floors

**Lens:** `data-correctness` · **Severity:** LOW · **Effort:** small

- **Where:** frontend/src/pages/CustomersPage.tsx:75 (`n >= 20`) vs zarin/insights.py:274 and zarin/analytics.py:221 (MIN_CUSTOMERS_RETENTION = 50)
- **Observed:** The Customers page renders the top-5 concentration figure once the period has ≥20 paying customers, with the empty-state text «با کمتر از ۲۰ مشتری، عدد تمرکز گمراه‌کننده است». The concentration *alert* card and the page-level `low_n` flag both use 50 (config.py:43).
- **Impact:** For merchants with 20-49 customers, the concentration number is shown on one surface as reliable enough to display while the engine simultaneously flags the same period as low-n. Minor, but it is a threshold that lives in config for exactly this reason.
- **Recommended fix:** Drive the CustomersPage gate from a value served by the API (or reuse `d.low_n`) rather than a hard-coded 20.

### ZB-108 · Cohort retention cells render percentages with no per-cohort sample floor, contradicting the documented MIN_SEGMENT_N rule

**Lens:** `statistics` · **Severity:** LOW · **Effort:** small

- **Where:** frontend/src/components/charts.tsx:159-172 (FragmentRow); zarin/analytics.py:197-208
- **Observed:** Live: M60 (59 customers, page-level low_n false) yields cohort cells such as 2026-02 k=4 → active 1 / cohort_size 10, rendered as «۱۰٪»; M233 shows 1/21 → «۵٪». docs/ANALYTICS.md §7 states MIN_SEGMENT_N=30 means «زیر آن: نرخ هیچ سگمنتی نقل نمی‌شود», but no floor is applied per cohort — only the page-wide MIN_CUSTOMERS_RETENTION=50 gate. Separately, `first_month` is derived entirely from the 6-month window, so every pre-existing customer active in 2026-01 is booked as a new January cohort member (left truncation) with no flag; docs also claim concentration is hidden below 20 customers while the code uses 50.
- **Impact:** The densest small-sample surface in the product has the weakest suppression: a shaded heat-map cell labelled as a retention rate can rest on a single customer. Unflagged left truncation makes the first cohort structurally non-comparable to later ones.
- **Recommended fix:** Blank or grey any cohort row whose cohort_size < MIN_SEGMENT_N, reusing the existing constant; footnote that the first cohort month is left-truncated by the data window; reconcile the ANALYTICS.md 20-customer concentration claim with the 50 in config.py.

### ZB-109 · Evidence drawer returns the exact executed SQL and bind parameters to unauthenticated clients

**Lens:** `security` · **Severity:** LOW · **Effort:** small

- **Where:** zarin/registry.py:100-102 (`"sql": sql.strip(), "params": params`), surfaced in every /api/overview, /api/funnel, /api/insights, /api/peers response; typed at frontend/src/api.ts:5
- **Observed:** `curl '.../api/overview?m=M156'` returns evidence objects carrying the literal query text and its parameters; zarin/peers.py:61 additionally returns `where_sql` with the peer-selection predicate. Queries are parameterized, so this is disclosure rather than injection.
- **Impact:** Full mart schema and query structure (table names, columns including payer_card_key, predicates) are handed to any caller, which is exactly the reconnaissance an attacker wants if any future query builder is less careful. It is also unusual to expose to end-merchants.
- **Recommended fix:** Keep the traceability feature — it is a genuine product strength — but gate the `sql`/`params` fields on an authenticated session (or an explicit "transparency mode" flag) once auth exists, and continue serving definition/formula/caveats to everyone.

### ZB-110 · Non-ASCII X-Admin-Token header raises TypeError → 500 instead of 401

**Lens:** `security` · **Severity:** LOW · **Effort:** small

- **Where:** zarin/api.py:36 (`hmac.compare_digest(x_admin_token or "", ADMIN_TOKEN)`)
- **Observed:** Verified in isolation: `hmac.compare_digest('Ã','s3cret')` raises `TypeError: comparing strings with non-ASCII characters is not supported`. Starlette decodes headers as latin-1, so any byte ≥0x80 in the header produces a non-ASCII str. Reachable only when ZARIN_ADMIN_TOKEN is set, so it could not be probed against the running server (token unset there).
- **Impact:** The guard still denies access, but an attacker can force unhandled 500s on every /api/admin/* route, poisoning the Product Performance error-rate panel (obs.py:47 counts status≥500) and hiding real errors.
- **Recommended fix:** Compare bytes: `hmac.compare_digest((x_admin_token or "").encode("utf-8", "ignore"), ADMIN_TOKEN.encode())`, and add a test case alongside tests/test_control.py:88.

### ZB-111 · Telemetry write failures are swallowed with no counter, and the event log never rotates

**Lens:** `reliability` · **Severity:** LOW · **Effort:** small

- **Where:** zarin/store.py:54-55, zarin/store.py:29-42
- **Observed:** `except OSError: pass  # telemetry must never break the request path` — correct priority, but nothing counts the drop, so a full disk or permission change stops the durable audit trail while the in-memory ring keeps the Control Center looking healthy. `_warm()` also reads the entire ai_events.jsonl at import (currently 48KB, append-only, no rotation) and silently `continue`s past corrupt lines with no count of what was skipped.
- **Impact:** Loss of the AI audit trail — the artifact backing the grounding/cost claims — is undetectable from inside the product.
- **Recommended fix:** Increment a `dropped` counter on OSError and a `corrupt_lines` counter in _warm(), and expose both in the AI-Ops summary; cap/rotate the JSONL by size.

### ZB-112 · Single global DuckDB lock with no query timeout — one slow query stalls the observability surface too

**Lens:** `reliability` · **Severity:** LOW · **Effort:** medium

- **Where:** zarin/db.py:14,63-66
- **Observed:** Every query serializes on a process-wide RLock held for the full `execute` + `fetchall`; there is no per-thread `con.cursor()` and no timeout. Measured live: 4 sequential /api/insights = 1.51s vs 4 parallel = 0.85s (a single call ≈0.38s), i.e. real contention, only partial overlap between the multiple queries each request issues. Documented as "thread-safe (RLock)" in docs/ARCHITECTURE.md:16, with the OLAP migration path in ADR-0001 — an acknowledged ceiling, not an accident.
- **Impact:** A pathological window or a mart rebuild landing mid-query blocks every endpoint including /api/admin/performance, so the Control Center goes down with the data layer rather than reporting on it; there is no bound on how long a request can hold the lock.
- **Recommended fix:** Use `connect().cursor()` per query (DuckDB cursors are thread-safe siblings) to drop the global lock to connection setup only, and add a statement timeout so one query cannot pin the process.

### ZB-113 · JSONL telemetry grows without bound and is fully re-parsed at every startup

**Lens:** `scalability` · **Severity:** LOW · **Effort:** small

- **Where:** zarin/store.py:29-42 (`EventLog._warm`) and :44-56 (`add`)
- **Observed:** `_warm()` reads and `json.loads` every line of `data/telemetry/ai_events.jsonl` on import purely to fill a `deque(maxlen=5000)`. No rotation, truncation or retention exists in the codebase. Current file: 48,316 bytes / 128 events ≈ 378 B/event. `add()` re-opens the file for append on every single event while holding the lock.
- **Impact:** Startup cost is O(total events ever), while only the last 5,000 survive — 1 M events (~380 MB) would be parsed and discarded on every restart. The per-event open/write/close under a lock also serialises AI telemetry writes with the copilot response path.
- **Recommended fix:** Seek to the tail (read the last ~N × 1 KB) in `_warm()` instead of the whole file, and rotate or truncate the JSONL at a size cap (`maxlen × avg_size`); keep a single open file handle with periodic flush rather than reopening per event.

### ZB-114 · Three orphan surfaces: cross-source insights are dead code, the OpsAI intent panel is unreachable in the default config, and the dormant-customer panel names a segment it cannot list

**Lens:** `product` · **Severity:** LOW · **Effort:** small

- **Where:** zarin/control.py:116; frontend/src/ops/OpsAI.tsx:81; frontend/src/pages/CustomersPage.tsx:88-96
- **Observed:** control.py:116 hardcodes `"cross_source_insights": []` unconditionally — `zarin/sources/insights.py::cross_source` is exercised only by tests/test_sources.py and is never called from any production path, so OpsSources.tsx:61-75 renders a section that can never populate even with GA4 connected. OpsAI.tsx:81 gates the intent-distribution panel on `d.models.length > 0`; live /api/admin/ai-ops returns `models: []` with 13 populated intents, so in the default offline mode the highest-value ops signal (fallback = 29/91) is computed and then never displayed. CustomersPage's dormant panel prints a count and total GMV, calls them "بهترین هدف برای کمپین بازگشت", and offers no list, filter, or export.
- **Impact:** Three places where the UI promises a capability the build cannot deliver. Individually small, but they are exactly the "orphan feature" pattern that erodes trust in the rest of the surface, and the OpsAI gating hides the one number that would have told the team their chat coverage is thin.
- **Recommended fix:** Wire cross_source into control.sources() behind the existing web_connected check (or delete the module and its UI section); gate the intent panel on `d.intents?.length` rather than models; give the dormant panel the same drill-through the evidence drawer already implements.

### ZB-115 · Chat-first landing over-promises relative to a 7-intent regex router; the flagship metric is not askable

**Lens:** `business` · **Severity:** LOW · **Effort:** small

- **Where:** zarin/copilot.py:39-131 (_plan) — 7 regex intents, then a generic overview fallback at line 124
- **Observed:** Called _plan() directly (curl mangles Persian on this shell): «چقدر پرداخت تایید نشده دارم؟» → intent=fallback, «کدام بانک بیشترین خطا را دارد؟» → fallback (issuer_bank_code exists in the attempts mart and is unused by the copilot), «بهترین محصولم چیست؟» → fallback. Live /api/admin/ai-ops shows fallback as the largest intent: 29 of 92 recorded requests. The landing page (docs/screenshots/rd-chat.png) presents an open Persian prompt plus a microphone.
- **Impact:** The chat surface is the first thing a merchant meets and it is framed as open-ended. Roughly a third of real questions return a canned summary — including a direct question about the 61.8B IRR figure displayed immediately above the input box. That mismatch reads as "the AI is fake" and undercuts the (otherwise correct) deterministic-first architecture.
- **Recommended fix:** Add a paid_unverified intent and an issuer-bank intent — both are one query each against existing marts. Then make the fallback honest and useful: name the topics it does cover instead of returning a period summary, so the failure mode reads as scope rather than incompetence.

### ZB-116 · Login accepts empty input and implies a real SMS; the documented login screenshot no longer matches the code

**Lens:** `ux` · **Severity:** LOW · **Effort:** small

- **Where:** frontend/src/pages/Login.tsx:75-100; docs/screenshots/rd-login.png
- **Observed:** The phone form submits with an empty field (line 75 has no validation) and the OTP form calls onLogin unconditionally (line 83) even with all five boxes blank. Line 85 then tells the user «کد ۵ رقمی پیامک‌شده به 0912 345 6789 را وارد کنید» using the hard-coded placeholder from line 20 when no number was typed, and line 80 states «با حساب زرین‌پال خود وارد شوید» — with no demo notice anywhere. Separately, rd-login.png shows a single phone screen with a role hint («بسته به نقش حساب شما، پس از ورود به فضای مناسب هدایت می‌شوید») and two chips, whereas the shipped Login.tsx opens on a choose-your-workspace step (:32-59).
- **Impact:** A first-run merchant waits for an SMS that will never arrive, or is confused by being told a code was sent to a number they never entered. Reviewers reading docs/screenshots see a login flow the build no longer has.
- **Recommended fix:** Require 10-11 digits before enabling «دریافت کد ورود» and require 5 filled boxes before «ورود»; add one line «نسخه نمایشی — هر کد ۵ رقمی وارد شود». Regenerate rd-login.png (and rd-mobile.png, whose bottom nav shows 6 of the 7 current nav items) from the current build.

### ZB-117 · KPI strip values lose their shared baseline whenever a value wraps or a tile has no footer line

**Lens:** `design` · **Severity:** LOW · **Effort:** small

- **Where:** frontend/src/theme.css:212-228 (.stats / .stat); visible in rd-overview.png, rd-customers.png, rd-mobile.png
- **Observed:** .stat is a flex column with justify-content:space-between, so the .v position depends on whether .k wraps and whether a .d/.foot line exists. rd-overview.png: «۱٫۹۵ هزار میلیارد» wraps to two lines and sits ~29px above the four single-line neighbours in the same strip. rd-customers.png: the four values land on two different baselines (۲۳,۸۰۱ and ۳۵٫۸٪ vs ۴۰٫۶٪ and ۲۸) because tiles 3 and 4 carry no sub-line. rd-mobile.png repeats it in the 2×2 glance grid.
- **Impact:** The most prominent numbers on the landing screen read as a ragged row rather than a scannable strip — the one place where a shared baseline does the most work. The .kpi-grid comment at theme.css:406 shows the team already recognised the sibling problem (orphaned cards) but not this one.
- **Recommended fix:** Give .stat a 3-row subgrid (label / value / footer) or reserve the footer line with a min-height and let the label clamp to one line with a title attribute, so .v always starts at the same offset within a strip.

### ZB-118 · Bottom of the type scale is too small for Persian, and the topbar merchant selector truncates mid-word

**Lens:** `design` · **Severity:** LOW · **Effort:** small

- **Where:** frontend/src/theme.css:142 (.bn-item 9.5px), :84/:339 (0.68rem), :48 chip fontSize 9; frontend/src/App.tsx:120-121 (select maxWidth 190)
- **Observed:** The mobile bottom nav labels are 9.5px — in rd-mobile.png «مشتری/مشابه/تغییر» are visibly at the legibility floor. Several other roles sit at 0.68rem (~10.9px): .side-brand .sub, .composer-note, .login-foot; CustomersPage.tsx:48 overrides a chip to 9px inline. Separately, the native `<select>` is capped at maxWidth:190px, so every rd-* screenshot's topbar shows "M156 — بیشترین فروش مو" cut mid-word with no ellipsis affordance.
- **Impact:** Persian script has no cap-height cue and thin connecting strokes, so it loses legibility earlier than Latin at the same px — the 9.5px nav is the weakest typographic moment in the product. The clipped selector label is the first thing the eye hits in the topbar on every screen.
- **Recommended fix:** Floor the scale at ~11px (raise .bn-item to 10.5–11px and drop to icon-only below ~360px), and either widen the select to ~240px, shorten the option text to the merchant key plus category, or replace it with a custom trigger showing the key with the description on a second line.

### ZB-119 · Legitimate roundings rejected; no cache or quota on the outbound LLM path

**Lens:** `ai-grounding` · **Severity:** LOW · **Effort:** small

- **Where:** zarin/ai/gateway.py:43-53 (false rejection); zarin/api.py:145-151 (/api/copilot — only MAX_QUESTION_LEN=500 applies)
- **Observed:** is_grounded('نرخ تبدیل حدود ۵۴ درصد بود', det containing ۵۴٫۵٪) → False: a natural "about 54%" rephrase is discarded, the behaviour ADR-0002:33 acknowledges. Separately /api/copilot has no per-merchant rate limit, no dedupe/cache of identical questions and no daily budget — each call is one outbound provider request. Unverified: with no key on this server (llm_requests=0 of 130 events) the guard's real-world accept/reject rate could not be measured.
- **Impact:** Higher-than-necessary fallback rate degrades the LLM feature's value, while an unbounded call path can exhaust free-tier quota — enforce_free protects money but not rate limits.
- **Recommended fix:** Let an LLM run trace to a deterministic run when it is that run correctly rounded to fewer decimals AND carries the same unit; add an lru_cache keyed on (merchant, question, period) around gateway.explain plus a per-merchant daily call ceiling.

