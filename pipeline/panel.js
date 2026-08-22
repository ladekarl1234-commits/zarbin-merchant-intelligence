export const meta = {
  name: 'zarbin-expert-panel-r1',
  description: 'Round-1 expert judging panel: 16 independent lenses score the deployed Zarbin, then every critical/high finding is adversarially verified',
  phases: [
    { title: 'Judge', detail: '16 independent expert lenses' },
    { title: 'Verify', detail: 'adversarial refutation of each critical/high finding' },
  ],
}

const CONTEXT = `
=== WHAT YOU ARE JUDGING ===

PRODUCT: "Zarbin" (زرین‌بین) — a Persian-language (RTL) merchant-payments intelligence
product built on an anonymised ZarinPal payments dataset (2.21M attempt rows → 2.06M
payment sessions, 343 merchants, 6 months). Two surfaces over one deterministic engine:
  * Merchant Workspace — insight-first dashboard for one merchant
  * Control Center — operator surface: platform health, product performance, AI operations, data sources

REPO (read it): C:\\Users\\pro\\OneDrive\\Desktop\\zarinpal   (Git Bash available; use
\`.venv/Scripts/python.exe\`; ALWAYS \`export PYTHONIOENCODING=utf-8\` before running anything
that prints Persian, or it will crash with a cp1252 error)
  zarin/            backend: pipeline, db, analytics, insights, peers, registry, copilot,
                    nlu (intent retrieval), cache, control, obs, auth, api, ai/*
  frontend/src/     React + Vite + TypeScript, RTL
  tests/            pytest
  docs/             ADRs, PLATFORM_BOOK, ANALYTICS, RETRIEVAL, DEPLOY_VERCEL, EXPERT_REVIEW (a
                    PREVIOUS panel's record), EXPERT_REVIEW_ISSUES (ZB-001..ZB-120)
  memory.md         engineering invariants — read this first, it is short and dense
  README.md

LIVE DEPLOYMENT (probe it — this is a real running system, not a mockup):
  https://zarbin-nine.vercel.app
  Merchant API is public: /api/meta /api/overview?m=M156 /api/insights?m=M156
  /api/funnel?m=M156 /api/customers?m=M156 /api/peers?m=M156
  /api/changes?m=M156&f1=&t1=&f2=&t2= /api/quality /api/evidence/sessions?m=M156
  /api/copilot?m=M156&q=<persian>            (deterministic, always)
  /api/copilot/polish?m=M156&q=<persian>     (optional LLM rephrasing, grounding-guarded)
  /api/docs  /api/openapi.json
  Control Center needs an ops session:
    TOKEN=$(curl -s -X POST 'https://zarbin-nine.vercel.app/api/auth/session?scope=ops' | python -c "import sys,json;print(json.load(sys.stdin)['token'])")
    curl -s -H "Authorization: Bearer $TOKEN" 'https://zarbin-nine.vercel.app/api/admin/platform'
    ... /api/admin/{platform,performance,ai-ops,sources,merchants,ai-eval,copilot?q=...}
  Every /api/* response carries \`Server-Timing: app;dur=<ms>\` — server-side cost, excluding
  your own network latency. USE IT; do not report wall-clock as if it were server time.

COMMANDS THAT WORK:
  .venv/Scripts/python.exe -m pytest -q                          # 180 tests
  .venv/Scripts/python.exe -m ruff check .
  .venv/Scripts/python.exe -m zarin.ai.eval.retrieval -v         # routing eval, before/after
  .venv/Scripts/python.exe pipeline/calibrate_nlu.py             # router calibration
  .venv/Scripts/python.exe -c "from zarin import copilot; print(copilot.answer('M156','...','2026-01-01','2026-06-30',use_llm=False))"
  cd frontend && npx tsc --noEmit

WHAT THE PRODUCT CLAIMS (these claims are what you are testing):
  1. Every number is computed by a deterministic engine and is traceable to definition,
     formula, executed SQL, params, sample size and caveats. The LLM may only rephrase and
     is never on the answer path.
  2. Grain: 1 dataset row = 1 payment ATTEMPT; all metrics are at SESSION grain. Retries
     never inflate counts or money.
  3. Success = session_status Verified. "Paid" = settled at bank but never verified by the
     merchant → reported separately as paid_unverified, REAL settled money, not an estimate.
  4. NoAttempt (try_seq=0) ≠ bank failure. Five/six behavioural outcomes are distinct.
  5. Opportunity = a counterfactual peer-gap estimate, capped at realized GMV, never
     "lost revenue = Σ failed amounts".
  6. adjusted_fee is NOT the real fee (a privacy multiplier is applied); it is only a
     relative index and must always be labelled as such.
  7. The copilot answers the question that was asked, or refuses and says why.
  8. It runs fully offline with no API key.

CONTEXT YOU MUST HAVE: a previous 15-lens panel scored commit 75de6bb at mean 73.4/100 and
236/300 on the competition rubric, and logged 120 findings (docs/EXPERT_REVIEW.md,
docs/EXPERT_REVIEW_ISSUES.md). Most were then fixed. You are judging the CURRENT state
(commit 5acf9e1). Do NOT re-report a finding that document already records as fixed unless
you VERIFY it is still present — and if you do, say so explicitly and show the evidence.

=== HOW TO JUDGE ===
Be adversarial. Assume the product is worse than it looks and hunt for the proof. A claim in
a README is not evidence; a command you ran and its output is. Read code, run it, and probe
the live deployment. Praise is only acceptable when it is specific and independently checked
— "the tests pass" is not a finding, "I ran X and it produced Y which contradicts claim Z" is.

SCORING BANDS (0-100), use the whole range:
  90-100 exceptional — production-grade for a real fintech at scale
  75-89  strong — clearly above typical hackathon/MVP work, minor gaps
  60-74  adequate — works and is defensible, real gaps a serious team would fix
  40-59  weak — deficiencies that would block production use
  0-39   poor
Justify the score by naming what keeps it from the band above AND what keeps it out of the
band below. A score with no "not higher because / not lower because" is not a judgement.

SEVERITY:
  critical — wrong money, a security hole, or a claim that is false in a way that misleads
  high     — a real defect a serious team would fix before shipping
  medium   — a defect worth a ticket
  low      — polish
`

const LENS_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['lens', 'score', 'confidence', 'summary', 'not_higher_because', 'not_lower_because', 'findings', 'verified_strengths'],
  properties: {
    lens: { type: 'string' },
    score: { type: 'integer', minimum: 0, maximum: 100 },
    confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
    summary: { type: 'string', description: '3-6 sentences. Concrete, with numbers you measured.' },
    not_higher_because: { type: 'string' },
    not_lower_because: { type: 'string' },
    findings: {
      type: 'array', maxItems: 10,
      items: {
        type: 'object', additionalProperties: false,
        required: ['severity', 'title', 'location', 'evidence', 'impact', 'fix'],
        properties: {
          severity: { type: 'string', enum: ['critical', 'high', 'medium', 'low'] },
          title: { type: 'string' },
          location: { type: 'string', description: 'file:line, endpoint, or UI surface' },
          evidence: { type: 'string', description: 'what you ran/read and what it produced. Exact output, not a paraphrase.' },
          impact: { type: 'string' },
          fix: { type: 'string', description: 'the smallest change that resolves it' },
        },
      },
    },
    verified_strengths: {
      type: 'array', maxItems: 5,
      items: { type: 'string', description: 'a strength you independently CHECKED, with the check' },
    },
  },
}

const LENSES = [
  { key: 'architecture', title: 'Technical architecture & engineering quality', focus: 'layering and its acyclicity, seams, coupling, the DuckDB/parquet choice against the alternatives in ADR-0001, the serverless deployment shape, whether the abstractions earn their keep, and whether a second engineer could change this safely.' },
  { key: 'code-quality', title: 'Code quality & maintainability', focus: 'readability, dead code, duplication (including across the Python/TypeScript boundary), naming, comment quality (are comments explaining WHY, or restating the code?), function size, error handling, and whether the codebase is smaller than the problem or larger.' },
  { key: 'data-correctness', title: 'Data & analytics correctness', focus: 'grain discipline, double counting, denominators, NULL arithmetic, window-vs-lifetime errors, the six outcomes partitioning sessions exactly, LMDI exactness, the realized-GMV cap on EVERY opportunity generator, and whether every displayed number equals what its SQL computes. Recompute things yourself from the marts.' },
  { key: 'statistics', title: 'Statistical methodology rigor', focus: 'sample-size gating, peer matching validity, whether intervals are honest (are the opportunity bands scenarios or confidence intervals, and is that labelled?), multiple comparisons, selection bias, the ntile/quantile choices, and any place a difference is presented as a finding when it is noise.' },
  { key: 'security', title: 'Security & privacy', focus: 'authn/authz on every endpoint, tenant scoping, the ops-session gate (mint one and try to reach data you should not), SQL injection, path traversal, prompt injection into the copilot, PII exposure through /api/evidence/sessions and the AI context, secrets in responses/telemetry/logs, security headers, and rate limiting. ACTIVELY ATTACK the live deployment.' },
  { key: 'reliability', title: 'Reliability, error handling & observability', focus: 'what happens on bad input at every trust boundary (probe the live API with malformed dates, huge limits, unknown merchants, 10KB questions, unicode), cold starts, the per-instance non-durable telemetry, whether errors are actionable, and whether the observability actually observes anything.' },
  { key: 'scalability', title: 'Scalability & performance', focus: 'the real measured latency using Server-Timing, the CDN cache design and whether it can serve stale or wrong data, memory footprint, the 63 MB bundle, concurrency behaviour of the DuckDB layer, what breaks at 10x and 100x the dataset, and whether the caching hides a slow query rather than fixing it.' },
  { key: 'product', title: 'Product quality', focus: 'does a merchant get a decision, not a dashboard? coverage (how many of the 343 merchants get useful cards — MEASURE IT), the insight→action last mile, restraint vs emptiness, and whether the two surfaces are genuinely different products.' },
  { key: 'business', title: 'Business viability & value proposition', focus: 'would a PSP pay for this? what is genuinely differentiated vs repackaged BI? what would block a real pilot? quantify the value the product surfaces (e.g. platform-wide paid_unverified) and sanity-check that number yourself.' },
  { key: 'ux', title: 'UX & usability for a non-technical merchant', focus: 'read the actual Persian strings the product emits. Is the language plain? Does a shop owner understand what to do? Are caveats readable or buried? What happens on an empty state, an error, a refused question? Fetch real copilot answers and judge them AS A MERCHANT WOULD.' },
  { key: 'design', title: 'Visual & interaction design, Persian/RTL craft', focus: 'read frontend/src/theme.css and the components. Token discipline, logical vs physical properties, RTL correctness, Persian numeral and separator consistency (there are two thousands separators in Persian — check both sides of the language boundary), chart honesty, and whether the merchant and ops surfaces are visually distinguishable.' },
  { key: 'accessibility', title: 'Accessibility & inclusive design', focus: 'WCAG 2.2 AA: compute the actual contrast ratios from the CSS tokens, keyboard reachability and focus order, focus trapping in the evidence drawer, aria usage, live regions, target sizes, reduced motion, and whether the voice input has a non-voice path.' },
  { key: 'ai-grounding', title: 'AI quality, grounding & AI-Ops', focus: 'try to BREAK the grounding guard with a fake provider (zarin/ai/gateway.py grounding_failure). Invented causality, unit swaps, rescaled numbers, dropped negations, injected links, empty output, English output. Then judge whether the AI-Ops surface reports honestly, whether the eval can fail, and whether the LLM-off-the-answer-path design is a real engineering decision or an excuse.' },
  { key: 'retrieval-eval', title: 'Retrieval quality and evaluation methodology', focus: 'read docs/RETRIEVAL.md, zarin/nlu.py, zarin/ai/eval/retrieval*.py. Is the evaluation methodology sound or self-serving? Are the two question sets really blind? Is the baseline fair? Are the constants really calibrated without touching the eval sets? Run the eval. Then write 25 NEW Persian questions of your own that neither set contains, route them with copilot.route_intent, and report the accuracy YOU measure.' },
  { key: 'testing-qa', title: 'Testing & quality assurance', focus: 'do the tests test behaviour or implementation? what is untested (measure coverage if you can)? are there tests that cannot fail? mutation-test by hand: change a constant or invert a condition in zarin/ and see whether any test catches it — DO THIS AT LEAST 5 TIMES and REVERT each change immediately. Report which mutations survived.' },
  { key: 'rubric-official', title: 'The official competition rubric, 300 points', focus: `Score the five criteria of the competition rubric and give a total out of 300:
    * Actionability & novelty of insights — 90 pts
    * Correctness & traceability — 75 pts
    * Analytical depth — 60 pts
    * Non-technical UX — 45 pts
    * Technical quality & executability — 30 pts
  The previous panel awarded 76/58/41/36/25 = 236/300 on commit 75de6bb. State each criterion's
  award, the reasoning, and what specifically changed since. Put the five awards and the total
  in your \`summary\` field in the exact form "A=<n>/90 C=<n>/75 D=<n>/60 U=<n>/45 T=<n>/30 TOTAL=<n>/300".
  Your \`score\` field must be the total as a percentage rounded to an integer.` },
]

phase('Judge')
const reviews = await parallel(LENSES.map((L) => () =>
  agent(
    `${CONTEXT}\n\n=== YOUR LENS ===\nYou are the \`${L.key}\` expert: **${L.title}**.\n\n` +
    `FOCUS: ${L.focus}\n\n` +
    `You are ONE lens on a panel. Judge only your dimension; other lenses cover theirs.\n` +
    `Spend your effort on VERIFICATION, not reading. Run things. Probe the live deployment.\n` +
    `Do not modify any file under zarin/, frontend/ or tests/ except a mutation you revert\n` +
    `immediately (testing-qa only). Scratch files go in pipeline/_panel/.\n` +
    `Set lens="${L.key}".`,
    { label: `lens:${L.key}`, phase: 'Judge', schema: LENS_SCHEMA }
  )
))

const ok = reviews.filter(Boolean)
log(`${ok.length}/${LENSES.length} lenses returned`)
const all = ok.flatMap(r => (r.findings || []).map(f => ({ ...f, lens: r.lens })))
const severe = all.filter(f => f.severity === 'critical' || f.severity === 'high')
log(`${all.length} findings, ${severe.length} critical/high to verify`)

phase('Verify')
const VERDICT_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['refuted', 'verdict', 'what_i_ran', 'corrected_severity'],
  properties: {
    refuted: { type: 'boolean', description: 'true if the finding is WRONG, overstated, or already handled' },
    verdict: { type: 'string', description: 'one paragraph: what you found' },
    what_i_ran: { type: 'string', description: 'the exact command(s)/file(s) and their output' },
    corrected_severity: { type: 'string', enum: ['critical', 'high', 'medium', 'low', 'not-a-defect'] },
  },
}

const verdicts = await parallel(severe.slice(0, 40).map((f, i) => () =>
  agent(
    `${CONTEXT}\n\n=== YOUR JOB: REFUTE THIS FINDING ===\n` +
    `Another reviewer claims the following. Your job is to try to prove them WRONG. Reproduce\n` +
    `their claim exactly. If it does not reproduce, if it is overstated, if the code already\n` +
    `handles it, or if the severity is inflated, say so — that is a successful refutation and\n` +
    `it is what you are here for. Only confirm what you can reproduce yourself.\n` +
    `Default to refuted=true when you cannot reproduce it.\n\n` +
    `LENS: ${f.lens}\nSEVERITY CLAIMED: ${f.severity}\nTITLE: ${f.title}\n` +
    `LOCATION: ${f.location}\nEVIDENCE CLAIMED: ${f.evidence}\nIMPACT CLAIMED: ${f.impact}`,
    { label: `verify:${i + 1}:${f.lens}`, phase: 'Verify', schema: VERDICT_SCHEMA }
  ).then(v => ({ finding: f, verdict: v }))
))

const checked = verdicts.filter(Boolean)
const confirmed = checked.filter(v => v.verdict && !v.verdict.refuted)
const refuted = checked.filter(v => v.verdict && v.verdict.refuted)
log(`verification: ${confirmed.length} confirmed, ${refuted.length} refuted, of ${checked.length} checked`)

const scores = ok.map(r => ({ lens: r.lens, score: r.score, confidence: r.confidence }))
const mean = scores.length ? scores.reduce((a, b) => a + b.score, 0) / scores.length : null

return {
  round: 1,
  lenses: ok.map(r => ({
    lens: r.lens, score: r.score, confidence: r.confidence, summary: r.summary,
    not_higher_because: r.not_higher_because, not_lower_because: r.not_lower_because,
    verified_strengths: r.verified_strengths,
    findings: r.findings,
  })),
  scores,
  mean_score: mean ? Math.round(mean * 10) / 10 : null,
  finding_counts: {
    total: all.length,
    critical: all.filter(f => f.severity === 'critical').length,
    high: all.filter(f => f.severity === 'high').length,
    medium: all.filter(f => f.severity === 'medium').length,
    low: all.filter(f => f.severity === 'low').length,
  },
  verification: {
    checked: checked.length,
    confirmed: confirmed.map(v => ({ lens: v.finding.lens, severity: v.verdict.corrected_severity,
                                     title: v.finding.title, location: v.finding.location,
                                     evidence: v.finding.evidence, fix: v.finding.fix,
                                     verdict: v.verdict.verdict })),
    refuted: refuted.map(v => ({ lens: v.finding.lens, title: v.finding.title,
                                 why: v.verdict.verdict, ran: v.verdict.what_i_ran })),
  },
}
