// 15-judge adversarial jury + meta-jury for the Zarbin submission.
// Each judge scores /300 independently (never sees another judge's score) then a
// meta-jury synthesizes. Run via the Workflow tool.
export const meta = {
  name: 'zarbin-jury',
  description: '15 decorrelated judges score the Zarbin submission /300, then a meta-jury synthesizes',
  phases: [{ title: 'Judges' }, { title: 'MetaJury' }],
};

const REPO = 'C:\\\\Users\\\\pro\\\\OneDrive\\\\Desktop\\\\zarinpal';
const SHOTS = REPO + '\\\\docs\\\\screenshots';

const SHARED = `
You are one judge on an adversarial competition panel for a ZarinPal hackathon submission.
PROJECT: "Zarbin" (زرین‌بین) — a Persian-first RTL Merchant Intelligence & Action Engine over a
payments dataset (2,213,289 payment attempts / 2,062,839 sessions / 343 merchants / 5 categories /
Jan–Jun 2026). Repo: ${REPO}. The dev server is RUNNING at http://localhost:8630 (API under /api/*).
Screenshots of every screen (desktop desk-*.png, mobile mob-*.png, tablet tab-*.png) are in ${SHOTS}.

OFFICIAL RUBRIC (score EVERY sub-criterion, conservatively, evidence-only — no credit for intentions):
- Actionability & novelty of insights: /90
- Correctness & traceability: /75
- Analytical depth: /60
- Non-technical merchant UX: /45
- Technical quality & executability: /30
Total /300. A perfect sub-score means you could find NO reason to deduct.

Inspect the REAL artifacts your lens needs (read files, read screenshots with the Read tool, and/or
curl the running API e.g. \`curl -s "http://localhost:8630/api/insights?m=M156"\`). Do NOT trust any
report. Be ruthless: assume competitors are excellent and judges skeptical. If an area is clean, say
what you actually checked. Keep prose tight.`;

const SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['judge', 'total', 'subscores', 'strongest', 'weaknesses', 'top_fixes'],
  properties: {
    judge: { type: 'string' },
    total: { type: 'integer', minimum: 0, maximum: 300 },
    subscores: {
      type: 'object', additionalProperties: false,
      required: ['actionability', 'correctness', 'depth', 'ux', 'technical'],
      properties: {
        actionability: { type: 'integer', minimum: 0, maximum: 90 },
        correctness: { type: 'integer', minimum: 0, maximum: 75 },
        depth: { type: 'integer', minimum: 0, maximum: 60 },
        ux: { type: 'integer', minimum: 0, maximum: 45 },
        technical: { type: 'integer', minimum: 0, maximum: 30 },
      },
    },
    strongest: { type: 'string' },
    weaknesses: { type: 'array', items: { type: 'string' } },
    top_fixes: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        required: ['fix', 'severity', 'points', 'evidence'],
        properties: {
          fix: { type: 'string' },
          severity: { type: 'string', enum: ['P0', 'P1', 'P2'] },
          points: { type: 'integer', minimum: 0, maximum: 90 },
          evidence: { type: 'string' },
        },
      },
    },
  },
};

const JUDGES = [
  ['J1 Official Rubric Judge', 'Score exactly as the official ZarinPal judge. Weight each rubric line. Pinpoint precisely where each deduction comes from and how many points.'],
  ['J2 Ruthless Data Scientist', 'Try to PROVE the analytics wrong. Attack grain, sessions-vs-attempts, success defs, retry/recovery, NoAttempt, Paid-vs-Verified, Reversed, customer identity/scoping, repeat metrics, cohort logic, denominators, active periods, missingness, outliers, concentration, confounders, sample-size handling. Curl the API and cross-check counts. Hunt silent statistical lies. Read zarin/pipeline.py, analytics.py.'],
  ['J3 Statistical Methodology Reviewer', 'Would a serious quant sign their name under this? Review peer methodology, counterfactual opportunity, confidence ranges, LMDI decomposition (zeros/exact-sum), percentiles/ties, temporal like-for-like, Simpson\'s paradox, selection bias, small samples, multiple comparisons, correlation-vs-causation, false precision. Read zarin/peers.py, insights.py, analytics.py, docs/ANALYTICS.md.'],
  ['J4 Actionability & Business Value', 'Would a real merchant CHANGE A DECISION after seeing this? Curl /api/insights for M156, M43, M265, M208. Look for generic/non-actionable/vague/unquantified insights, fake precision, repetition, low-value metrics, missed opportunities. Judge whether each card ends in a specific number AND a concrete action.'],
  ['J5 Novelty Judge', 'Assume competitors build charts/funnels/retention/cohorts/comparison dashboards. Is Zarbin genuinely memorable? Weigh paid-but-unverified intelligence, payment rescue, LMDI root-cause, explainability drawers, counterfactual opportunity, matched peers, deterministic copilot. If not distinctive enough, say what specifically is missing.'],
  ['J6 Traceability / Auditability', 'Challenge every major number: Insight→metric→definition→formula→actual query→filter→sample size→source sessions. Curl /api/overview and /api/evidence/sessions for M156. Open a screenshot of the evidence drawer if present. Find numbers whose evidence is incomplete, misleading, stale, or inconsistent. Read zarin/registry.py, api.py.'],
  ['J7 Non-technical Merchant UX', 'You own a normal Iranian shop and know almost nothing about analytics. Read desk-overview.png, mob-overview.png. Do I understand what happened, why, what to do, the money amount, the confidence? Am I overwhelmed? Do technical words (Verified/InBank/LMDI/PSP) leak without explanation? Do charts require interpretation? Penalize complexity hard.'],
  ['J8 World-Class Product Designer', 'Inspect the RENDERED product (read desk-overview.png, desk-funnel.png, desk-changes.png, desk-peers.png, desk-customers.png). Judge hierarchy, information architecture, whitespace, typography, Persian type, color, density, cards, charts, motion cues, polish, originality, premium feel. Does this look world-class or like a polished hackathon dashboard? Be ruthless about generic/templated aesthetics.'],
  ['J9 Persian RTL & Localization', 'Read desk-overview.png, desk-funnel.png, desk-changes.png, mob-overview.png. Check RTL correctness, Persian readability, punctuation, mixed fa/en strings, number direction, IRR formatting, dates (Jalali), chart labels, reversed strings, awkward machine Persian. Flag any visually reversed or broken text.'],
  ['J10 Mobile Product Judge', 'Read mob-overview.png, mob-funnel.png, mob-customers.png, mob-peers.png, mob-copilot.png. Judge real hierarchy (not just "it fits"): navigation, insights, charts, tables, touch targets, scroll, sticky elements. Does mobile feel intentionally designed? Curl nothing; judge visuals + read frontend/src/theme.css media queries.'],
  ['J11 Accessibility Judge', 'Review keyboard nav, focus management, drawer/modal trapping + Escape, semantic HTML, ARIA, contrast, reduced motion, screen-reader meaning, non-color-only status, touch size. Read frontend/src/components/EvidenceDrawer.tsx, ui.tsx, theme.css. Do not treat a11y as optional.'],
  ['J12 Senior Software Architect', 'Review architecture, module boundaries, type safety, metric centralization, query organization, performance, caching, pipeline, stale-mart handling, reproducibility, config, error handling, dependencies. Read zarin/db.py, api.py, config.py, pipeline.py, pyproject.toml. Find hackathon shortcuts that create judge-visible fragility.'],
  ['J13 Security & Privacy Red-Team', 'Payments-data product. Attack path traversal, UNC paths, static serving, SQL injection, query validation, malformed dates, limits, arbitrary file access, CORS/CSRF, localhost binding, data exposure, source-session evidence scope, secrets, repo history, dataset leakage. Curl probes are allowed (non-destructive). Read zarin/api.py, db.py; check git ls-files and history for dataset/secrets.'],
  ['J14 Reproducibility / DevEx', 'Can a judge run this in minutes with no team contact? Read README.md fully. Check exact commands, data placement, uv, Docker, Node requirement, Windows, first-run pipeline, startup time, LOCAL URL visibility, VS Code experience (.vscode present?). Any confusing step or stale/placeholder command costs points. Flag "git clone <this-repo>" style placeholders.'],
  ['J15 Demo & Submission Judge', 'You have minutes. Read desk-overview.png first. Judge first-30-seconds wow, problem clarity, strongest demo merchant, sequencing, memorable insight, traceability moment, desktop+mobile demo, credibility, ending. Read docs/DEMO_SCRIPT.md. Does the demo make you want to give first place?'],
];

phase('Judges');
const results = await parallel(JUDGES.map(([name, lens]) => () =>
  agent(`${SHARED}\n\nYOUR LENS — ${name}:\n${lens}\n\nReturn your structured score now. \`judge\` MUST be "${name}". Score all five sub-scores so they sum to \`total\`. List concrete weaknesses and top_fixes (each with severity P0/P1/P2, the rubric points it would recover, and evidence: a file/screen/endpoint).`,
    { label: name, phase: 'Judges', schema: SCHEMA })
    .then((r) => r).catch(() => null)));

const valid = results.filter(Boolean);
log(`Judges returned: ${valid.length}/15`);

phase('MetaJury');
const meta_out = await agent(
  `${SHARED}\n\nYou are the META-JURY. Here are all ${valid.length} independent judge scorecards as JSON:\n\n` +
  JSON.stringify(valid, null, 1) +
  `\n\nProduce a synthesis. Compute min/median/mean/max of \`total\`. State the CONSERVATIVE expected score (NOT the max — weight toward the lower scores and the recurring deductions). Identify: recurring deductions (raised by ≥3 judges), notable disagreements, the TOP 10 point-loss risks ranked by (expected points recovered ÷ implementation risk), and which are P0/P1/P2. Be honest — a credible 292 beats a dishonest 300. Return prose (no schema), ≤1500 tokens, structured with clear headers.`,
  { label: 'meta-jury', phase: 'MetaJury' });

return { judges: valid, meta: meta_out };
