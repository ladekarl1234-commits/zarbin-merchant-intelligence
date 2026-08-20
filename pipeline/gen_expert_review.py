"""Generate docs/EXPERT_REVIEW.md + docs/EXPERT_REVIEW_ISSUES.md from the archived panel results.

Two modes:
  python pipeline/gen_expert_review.py
      Regenerate both Markdown documents from docs/expert_review_findings.json (the committed
      archive). This is the reproducible path — it works on any machine, from the repo alone.

  python pipeline/gen_expert_review.py --from-raw <workflow-output.json>
      One-time import: build docs/expert_review_findings.json from the raw workflow output, then
      generate the documents. The raw file is a session-scoped artifact and is not committed.

Everything in the generated documents comes from the archive, except the clearly-labelled
hand-written sections (final assessment, limitations, addendum), which live in this file.
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_MD = ROOT / "docs" / "EXPERT_REVIEW.md"
OUT_ISSUES = ROOT / "docs" / "EXPERT_REVIEW_ISSUES.md"
ARCHIVE = ROOT / "docs" / "expert_review_findings.json"

LENS_ORDER = ["rubric-official", "architecture", "code-quality", "data-correctness", "statistics",
              "security", "reliability", "scalability", "product", "business", "ux", "design",
              "accessibility", "ai-grounding", "testing-qa"]
LENS_TITLE = {
    "rubric-official": "Official competition rubric (300 pts)",
    "architecture": "Technical architecture & engineering quality",
    "code-quality": "Code quality & maintainability",
    "data-correctness": "Data & analytics correctness",
    "statistics": "Statistical methodology rigor",
    "security": "Security & privacy",
    "reliability": "Reliability, error handling & observability",
    "scalability": "Scalability & performance",
    "product": "Product quality",
    "business": "Business viability & value proposition",
    "ux": "UX & usability (non-technical merchant)",
    "design": "Visual & interaction design, Persian/RTL craft",
    "accessibility": "Accessibility & inclusive design",
    "ai-grounding": "AI quality, grounding & AI-Ops",
    "testing-qa": "Testing & quality assurance",
}
SEV_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
SEV_LABEL = {"critical": "CRITICAL", "high": "HIGH", "medium": "MEDIUM", "low": "LOW"}
NOT_VERIFIED = "not verified (verification pass covered critical/high only)"


def clean(s) -> str:
    return "" if s is None else html.unescape(str(s)).replace("\r", "").strip()


def build_archive(raw_path: Path) -> dict:
    """One-time import from the raw workflow output into a self-contained archive."""
    data = json.loads(raw_path.read_text(encoding="utf-8"))["result"]
    lenses, stats = data["lenses"], data["stats"]
    for i, L in enumerate(lenses):
        L["_key"] = LENS_ORDER[i] if i < len(LENS_ORDER) else f"lens{i}"

    issues = []
    for L in lenses:
        for f in L.get("findings", []):
            issues.append({**f, "_lens": L["_key"]})
    issues.sort(key=lambda f: (SEV_RANK.get(f.get("severity"), 9),
                               LENS_ORDER.index(f["_lens"]) if f["_lens"] in LENS_ORDER else 99))

    return {
        "commit": "75de6bb",
        "panel": {"lenses": len(lenses), "agents_total": 58, "verification_agents": 43},
        "stats": stats,
        # full narrative archived so the documents are reproducible from this file alone
        "scores": [{"lens": L["_key"], "dimension": clean(L.get("dimension")), "score": L.get("score"),
                    "confidence": L.get("confidence"), "summary": clean(L.get("summary")),
                    "scoring_rationale": clean(L.get("scoring_rationale")),
                    "strengths": [clean(s) for s in (L.get("strengths") or [])]} for L in lenses],
        "rubric": next((L["rubric"] for L in lenses if "rubric" in L), None),
        "issues": [{
            "id": f"ZB-{n:03d}", "lens": f["_lens"], "severity": f.get("severity"),
            "title": clean(f.get("title")), "location": clean(f.get("location")),
            "evidence": clean(f.get("evidence")), "impact": clean(f.get("impact")),
            "recommendation": clean(f.get("recommendation")), "effort": f.get("effort"),
            "verification": f.get("verdict") or NOT_VERIFIED,
            "verification_evidence": clean(f.get("verify_evidence"))[:600] or None,
            "verification_note": clean(f.get("verify_note"))[:600] or None,
        } for n, f in enumerate(issues, 1)],
    }


# --- hand-written sections (clearly labelled as such in the output) -------------------------------

FINAL_ASSESSMENT = """## 7. Final assessment

> Sections 7–9 are written by the engineer who integrated the panel's results, not generated from
> them. Every figure quoted here is either taken from the archive or measured directly, with the
> command shown.

**Overall: mean {mean}/100 across {n} dimensions; {rubric_total}/300 on the competition's own rubric.**
In the panel's calibration that is the top of "adequate" / bottom of "strong": a product whose
analytical core is genuinely good, whose engineering is tidy, and whose remaining problems are
concentrated in a few recurring themes rather than scattered randomly.

### What the panel consistently praised

The three highest scores are the analytical and engineering foundations — `code-quality` **82**,
`data-correctness` **82**, `architecture` **80** — and the praise is specific and independently
measured, not impressionistic. Each of the following is a measurement reported by the lens named:

- **Grain discipline holds** (`data-correctness`): no double-count, wrong denominator, silent NULL
  arithmetic or window-vs-lifetime error found in the SQL; verified live that 2,062,839 sessions =
  2,062,839 distinct `session_key`s, and that the six outcomes partition sessions exactly at both
  merchant and platform level.
- **The hard math is exact** (`statistics`): LMDI contributions sum to ΔGMV to ~1e-15 relative
  residual across four merchants; the conversion-driver identity closes to ~1e-17 including the
  `reversed` term.
- **The layering is real, not decorative** (`architecture`): every internal import mapped; the graph
  is strictly acyclic with zero upward imports, and the metric registry genuinely is the single
  source of truth for the merchant surface.
- **Restraint is implemented** (`product`): peers are suppressed rather than fabricated below the
  minimum pool, cards stay silent when evidence is thin, the opportunity engine refuses the
  "lost revenue = Σ failed amounts" fallacy, and the scenario band is explicitly labelled as *not*
  a confidence interval.
- **Deterministic-first AI is verified** (`ai-grounding`): 130 live telemetry events on the running
  server were 100% `source=deterministic`, and the product is fully correct with zero keys and zero
  network.
- **Persian-first craft is real** (`design`): one coherent token system, CSS logical properties
  throughout, deliberate LTR islands for SQL/formulas/time-axes, Jalali dates and Persian numerals.

### The one theme that explains most of the serious findings

Across five independent lenses the same failure shape appears: **a guarantee the product states is
enforced only partially, while the documentation states it unconditionally.** This is the most
important result of the review, because it attacks credibility rather than function:

| Stated guarantee | What is actually enforced | Issues |
|---|---|---|
| "Opportunity is capped at realized GMV" | The cap lives only inside `_gap_card` (`insights.py:86-93`), which serves `no_attempt_gap` and `inbank_gap`. `recovery_gap`, `high_value_friction` and `repeat_gap` produce rial estimates with **no cap and no `capped` flag** — a live card for M21 exceeds that merchant's entire six-month realized GMV (see the measurement below) | [ZB-006](EXPERT_REVIEW_ISSUES.md#zb-006) |
| Evidence drawer shows how a number was computed | For opportunity cards the printed formula and caveat describe an estimator the code no longer uses | [ZB-007](EXPERT_REVIEW_ISSUES.md#zb-007), [ZB-014](EXPERT_REVIEW_ISSUES.md#zb-014), [ZB-017](EXPERT_REVIEW_ISSUES.md#zb-017), [ZB-011](EXPERT_REVIEW_ISSUES.md#zb-011) |
| "The LLM may only rephrase; it can never change a number" | The guard inspects digit runs only — invented causality, invented advice, wrong units and arbitrary downscaling pass | [ZB-004](EXPERT_REVIEW_ISSUES.md#zb-004), [ZB-020](EXPERT_REVIEW_ISSUES.md#zb-020), [ZB-038](EXPERT_REVIEW_ISSUES.md#zb-038), [ZB-039](EXPERT_REVIEW_ISSUES.md#zb-039) |
| "Refusal safety 100%" in the AI evaluation | The refusal checks cannot fail as written, and the cases do not actually refuse | [ZB-040](EXPERT_REVIEW_ISSUES.md#zb-040) |
| Tests pin the dangerous invariants | 81% statement coverage measured by the `testing-qa` lens, but the peer-percentile happy path, six of nine card generators and ops-copilot routing are untested | [ZB-005](EXPERT_REVIEW_ISSUES.md#zb-005), [ZB-041](EXPERT_REVIEW_ISSUES.md#zb-041), [ZB-042](EXPERT_REVIEW_ISSUES.md#zb-042), [ZB-044](EXPERT_REVIEW_ISSUES.md#zb-044) |

The fix for this theme is mostly cheap — move one cap into the ranking loop, regenerate the registry
text from the code that computes it, extend the guard beyond digits (or soften the claim to what is
actually enforced), and make the eval assertions capable of failing.

#### The uncapped-opportunity measurement, in full

Measured directly against the live engine over the API's default range (2026-01-01..2026-06-30):

```
M21 high_value_friction impact_high = 4,696,769,634 IRR   capped=None
M21 realized GMV                    = 4,373,353,280 IRR
ratio                               = 107.4%
uncapped rial kinds present  : paid_unverified, high_value_friction, repeat_gap
kinds carrying a capped flag : no_attempt_gap, inbank_gap
```

`paid_unverified` is legitimately uncapped — it is a realized sum, not an estimate. The estimate-
bearing uncapped kinds are the problem. Note that `impact_high` for this card is **not stable across
runs** (see [ZB-120](#zb-120) in the addendum); observed values ranged 4.70–4.83 billion IRR over
five identical calls, i.e. 107–110% of realized GMV.

### Production-readiness gaps that are honest, but must not be understated

The security (**66**), scalability (**66**) and reliability (**70**) scores reflect deliberate
hackathon scope, not accidents — but the record documents them plainly: there is **no authentication
or authorization on any merchant data endpoint** and tenant scoping is a client-supplied `m=`
parameter ([ZB-001](EXPERT_REVIEW_ISSUES.md#zb-001), [ZB-030](EXPERT_REVIEW_ISSUES.md#zb-030)); a
process-wide `RLock` serializes every DuckDB query ([ZB-002](EXPERT_REVIEW_ISSUES.md#zb-002)); marts
are unclustered so each merchant query full-scans 2.06M sessions
([ZB-023](EXPERT_REVIEW_ISSUES.md#zb-023)). None of these blocks the challenge demo; all of them block
a real merchant-facing deployment, and the repository should not imply otherwise.

### Accessibility is the weakest dimension

At **61**, `accessibility` is the only dimension below the "adequate" band. The intent is visibly
there — a correct focus trap with restore, `aria-current`/`aria-pressed`, `lang="fa" dir="rtl"`, a
reduced-motion kill-switch — but conformance does not hold: computed contrast of the muted/body text
tokens fails WCAG 1.4.3 across every surface (mobile primary nav at 2.35:1), the chat composer's focus
indicator is removed, and seven zero-size invisible buttons sit in the tab order
([ZB-035](EXPERT_REVIEW_ISSUES.md#zb-035)–[ZB-037](EXPERT_REVIEW_ISSUES.md#zb-037)). These are small,
well-localized fixes with disproportionate value.

### An adjudicated disagreement (worth recording)

Two lenses appeared to contradict each other on merchant coverage: `rubric-official` measured that
56 of 60 merchants receive at least one insight card, while `business` reported that ~37% of merchants
see an empty dashboard ([ZB-003](EXPERT_REVIEW_ISSUES.md#zb-003)). Rather than picking a side, both
populations were measured directly (`zarin.insights.generate` over `merchant_stats ORDER BY gmv DESC
NULLS LAST, merchant_key`, range 2026-01-01..2026-06-30):

```
top-60 by GMV                      :   4/60  empty =  6.7%
systematic 1-in-5 across full range:  24/69  empty = 34.8%
FULL population                    : 126/343 empty = 36.7%
```

Both lenses were right about different populations: `rubric-official` sampled the head (4 empty of 60
≙ "56 of 60 receive a card"), `business` characterised the whole base. The head of the merchant
distribution is well served; the long tail — the merchants who most need help — is not, and the empty
state currently frames that silence as good news. The finding stands, with the nuance that it is a
**tail-coverage** problem, not a general one. (These counts move by ±2 between runs because of
[ZB-120](#zb-120).)

### Recommended order of work

1. **Stop publishing numbers that contradict themselves (small effort, highest value):** ZB-120,
   ZB-006, ZB-007/ZB-014/ZB-017/ZB-011, ZB-013, ZB-015.
2. **Honesty of the AI claim:** ZB-004/ZB-020/ZB-038/ZB-039 and ZB-040 — either strengthen the guard
   or narrow the documented claim to "numbers are deterministic; prose is model-generated".
3. **Test the untested invariants:** ZB-005, ZB-041, ZB-042, ZB-044.
4. **Accessibility conformance:** ZB-035, ZB-036, ZB-037.
5. **Tail coverage & follow-through:** ZB-003, ZB-026, ZB-027, ZB-031, ZB-032.
6. **Production hardening (large, only if this leaves the hackathon):** ZB-001/ZB-030, ZB-002, ZB-023.

**Bottom line.** This is a credible, unusually disciplined analytical product with a real
differentiator (settled-but-unverified money, surfaced as bankable and traceable) and an engineering
base that a team could keep building on. It is not yet a production merchant-facing service, and a
handful of its own stated guarantees are currently stronger in the documentation than in the code.
Closing that gap — not adding features — is what would move this from "strong hackathon product" to
"trustworthy".

---
"""

LIMITATIONS = """## 8. Limitations of this review

An honest record has to state what it does **not** establish:

- **The reviewers are AI agents.** {verified} of the {serious} critical/high findings were
  independently re-verified by a separate agent with cited evidence ({confirmed} confirmed,
  {refuted} refuted). **{unverified} findings were not verified**: the {medlow} medium/low findings,
  which were deliberately excluded from that pass, plus **ZB-044**, which the panel's per-lens
  verification cap dropped. Treat unverified findings as credible but unconfirmed.
- **Scores are calibrated judgement, not measurement.** The counts, coverage, timings and live API
  values quoted in the register are measured; the 0–100 dimension scores are expert opinion against a
  shared rubric and would move a few points with a different panel.
- **The rubric lens is inside the mean.** `rubric-official` (78.7 = 236/300 as a percentage) is both a
  summary of the product and a member of the population being averaged. Excluding it, the mean of the
  14 independent dimensions is **73.0** rather than {mean}.
- **No human usability testing.** UX, design and accessibility were assessed from source, computed
  contrast ratios and screenshots — not from watching a real merchant use the product, and not with a
  real screen reader.
- **Single dataset, single machine.** Performance and coverage figures come from the challenge dataset
  on one developer machine; they indicate shape, not production capacity.
- **Video and deployment were excluded by request**, so this review is explicitly *not* a
  production-readiness or release verdict.
- **Point-in-time.** Everything here describes commit `{commit}`. Fixes made after that commit are not
  reflected; re-running the panel is the intended way to update this record.

---

## 9. Addendum — found while verifying this record

After the panel finished, the published record was itself audited by an independent agent, and the
hand-written claims were re-measured. That pass corrected four numeric/claim defects in this document
(the M21 ratio, the top-60 coverage figure, the "every critical/high was verified" claim, and a
generator that could not actually regenerate anything) and surfaced one **new product defect** that
the panel had missed:

<a id="zb-120"></a>

### ZB-120 · `high_value_friction` is non-deterministic — the same query returns different money

**Lens:** `record-verification` · **Severity:** HIGH · **Effort:** small · **Verification:** measured directly

- **Where:** `zarin/insights.py:209` — `ntile(5) OVER (ORDER BY amount)`
- **Observed:** five identical calls to `generate('M21','2026-01-01','2026-06-30')` returned **four
  distinct** values for `high_value_friction.impact_high`:
  `4,813,687,678 / 4,763,212,124 / 4,829,335,319 / 4,763,212,124 / 4,712,497,933`.
- **Why:** `ntile(5) OVER (ORDER BY amount)` has no tiebreaker. Payment amounts tie constantly (round
  prices), so rows with equal `amount` land in different quintiles on different runs under DuckDB's
  parallel execution, changing `n_top`, `conv_top` and `avg_lost_amount`.
- **Impact:** This contradicts the product's central promise — "the same query, always the same
  answer" (ADR-0002) — on the very surface built to prove it. A merchant who reopens the card, or a
  judge who re-runs the evidence drawer, can see a different amount with no explanation. It also
  makes every downstream figure (ranking position, copilot answer text) irreproducible.
- **Recommended fix:** add a deterministic tiebreaker — `ntile(5) OVER (ORDER BY amount, session_key)`
  — and add a test asserting two consecutive `generate()` calls return identical `impact_high`.
  Audit the other window functions and any `ORDER BY` without a unique tiebreaker for the same class
  of bug.

### Corrections applied to this record

The agents' own text (sections 4, 5 and the register) is **preserved verbatim**, including where a
lens rounded differently — editing it would falsify the record. The corrections below therefore apply
to the hand-written sections and to the repository's summaries of them; where a number here differs
from an agent's wording above, this table is authoritative.

| Was published as | Corrected to | Why |
|---|---|---|
| "a live card claims 109% of the merchant's six-month sales" | 107.4% on the measured run; 107–110% across runs | The original rounded up past both its source (108%) and the measurement; the spread is itself ZB-120 |
| "top-60 by GMV: 3/60 empty = 5.0%" | 4/60 = 6.7% | Did not reproduce; also contradicted the panel's own "56 of 60" five lines above |
| "every critical/high finding was re-verified (43/43)" | 43 of 44 — ZB-044 was not verified | The panel capped verification at four findings per lens; `testing-qa` had five |
| "the cap covers one of four opportunity generators" | The cap lives only in `_gap_card`; `recovery_gap`, `high_value_friction`, `repeat_gap` are uncapped | "one of four" was ambiguous and understated the exposure |
| Generator credited as reproducible | Now reads the committed archive and uses repo-relative paths | It previously read a session-scoped temp file on an absolute path |
| 44 issue links | `<a id="zb-nnn">` anchors emitted in the register | The links resolved to the top of the file, not the issue |

---
"""


def render(a: dict) -> None:
    stats, sc = a["stats"], a["stats"]["severity_counts"]
    issues, scores, R = a["issues"], a["scores"], a["rubric"]
    serious = [i for i in issues if i["severity"] in ("critical", "high")]
    verified = [i for i in serious if i["verification"] in ("CONFIRMED", "REFUTED")]
    confirmed = sum(1 for i in verified if i["verification"] == "CONFIRMED")
    refuted = sum(1 for i in verified if i["verification"] == "REFUTED")
    unverified = len(issues) - len(verified)
    medlow = sc["medium"] + sc["low"]

    o = []
    w = o.append
    w("# Expert Panel Review — Zarbin (زرین‌بین)\n")
    w("An auditable record of an independent, multi-agent expert evaluation of this software.\n"
      "It documents **how** the review was run, **which** specialized lenses reviewed it, **what**\n"
      "they scored, **what they found**, and **what remains to be fixed** — not just a headline number.\n")
    w(f"> **Result at a glance** — {a['panel']['lenses']} expert lenses, **{stats['findings_total']} documented findings** "
      f"({sc['critical']} critical / {sc['high']} high / {sc['medium']} medium / {sc['low']} low), "
      f"mean dimension score **{stats['mean']}/100** (median {stats['median']}, range {stats['min']}–{stats['max']}). "
      f"Against the competition's own rubric: **{R['total']}/300**. "
      f"{len(verified)} of the {len(serious)} critical/high findings were independently re-verified "
      f"(**{confirmed} confirmed, {refuted} refuted**); see §8 for what was *not* verified. "
      f"A later audit of this record added one further defect — [ZB-120](#zb-120).\n")
    w("---\n")

    w("## 1. Scope and snapshot\n")
    w("| | |")
    w("|---|---|")
    w("| Product | Zarbin — dual-surface merchant intelligence for ZarinPal (Merchant Workspace + Operations Control Center) |")
    w(f"| Commit reviewed | `{a['commit']}` on `main` (25 commits) |")
    w("| Backend | 3,049 lines Python (`zarin/`) |")
    w("| Frontend | 2,341 lines TypeScript/TSX (`frontend/src/`) |")
    w("| Tests | 667 lines (`tests/`) |")
    w("| Documentation | 17 Markdown documents (`docs/`, `docs/ADR/`) |")
    w(f"| Panel | {a['panel']['agents_total']} agents total — {a['panel']['lenses']} expert lenses + "
      f"{a['panel']['verification_agents']} independent verification agents |\n")
    w("**Explicitly out of scope for this round** (excluded by request — not scored, no findings raised):\n"
      "the demo video, and deployment / hosting / release / CI-CD / infrastructure provisioning.\n"
      "Automated tests and code-level quality gates remained in scope; the evaluation targets the\n"
      "**software itself**.\n")
    w("---\n")

    w("## 2. How this review was produced\n")
    w("1. **15 specialized expert lenses** were run as independent agents, in parallel, against the same\n"
      "   commit. Each inspected the real source **and the live running product** (read-only: it could read\n"
      "   code, run the test suite, run the AI evaluation harness and call the local API — it could not\n"
      "   modify files, build, or restart anything).\n"
      "2. Each returned a **structured evaluation**: a 0–100 score for its dimension, an explicit rationale,\n"
      "   observed strengths, and findings — each with **severity, location, observed evidence, impact,\n"
      "   recommendation and effort**.\n"
      f"3. Findings rated **critical** or **high** were then handed to a **separate verification agent** which\n"
      f"   re-examined the actual code/behaviour and returned **CONFIRMED** or **REFUTED** with cited evidence.\n"
      f"   This pass was capped at four findings per lens, so it covered {len(verified)} of the {len(serious)}\n"
      f"   critical/high findings — ZB-044 was missed by that cap and is labelled accordingly.\n"
      "4. Aggregates are computed **deterministically** from the returned data — not estimated by a model.\n"
      "   Both Markdown documents are generated by `pipeline/gen_expert_review.py` from\n"
      "   [`expert_review_findings.json`](expert_review_findings.json), which archives the agents'\n"
      "   returned results verbatim; regenerate them at any time with:\n"
      "   ```bash\n   uv run python pipeline/gen_expert_review.py\n   ```\n")
    w("Scoring calibration given to every agent:\n")
    w("| Band | Meaning |")
    w("|---|---|")
    w("| 90–100 | Exceptional — production-grade for a real fintech at scale |")
    w("| 75–89 | Strong — clearly above typical hackathon/MVP work, minor gaps |")
    w("| 60–74 | Adequate — works and is defensible, real gaps a serious team would fix |")
    w("| 40–59 | Weak — deficiencies that would block production use |")
    w("| 0–39 | Poor |\n")
    w("---\n")

    w("## 3. Dimension scores\n")
    w("| # | Lens | Dimension | Score | Confidence | Findings |")
    w("|---:|---|---|---:|---|---|")
    for i, s in enumerate(scores, 1):
        c = {}
        for f in issues:
            if f["lens"] == s["lens"]:
                c[f["severity"]] = c.get(f["severity"], 0) + 1
        fs = " · ".join(f"{v} {k}" for k, v in sorted(c.items(), key=lambda kv: SEV_RANK[kv[0]])) or "—"
        w(f"| {i} | `{s['lens']}` | {LENS_TITLE.get(s['lens'], s['dimension'])} | "
          f"**{s['score']}** | {s['confidence']} | {fs} |")
    w("")
    w(f"**Aggregate:** mean **{stats['mean']}/100** · median **{stats['median']}** · "
      f"range **{stats['min']}–{stats['max']}** across {stats['n_lenses']} dimensions "
      f"(**73.0** excluding the rubric lens — see §8).\n")
    w("---\n")

    w("## 4. Against the competition's own rubric\n")
    w("The rubric from the original brief, scored by the dedicated `rubric-official` lens:\n")
    w("| Criterion | Awarded | Max | Reasoning |")
    w("|---|---:|---:|---|")
    for k, label in [("actionability", "Actionability & novelty of insights"),
                     ("correctness", "Correctness & traceability"),
                     ("depth", "Analytical depth"),
                     ("ux", "Nontechnical UX"),
                     ("technical", "Technical quality & executability")]:
        why = clean(R[k]["why"]).replace("|", "/").replace("\n", " ")
        w(f"| {label} | **{R[k]['awarded']}** | {R[k]['max']} | {why} |")
    w(f"| **Total** | **{R['total']}** | **300** | |\n")
    w("---\n")

    w("## 5. What each expert concluded\n")
    for s in scores:
        w(f"### {LENS_TITLE.get(s['lens'], s['dimension'])} — {s['score']}/100\n")
        w(f"*Lens `{s['lens']}` · confidence {s['confidence']}*\n")
        w(s["summary"] + "\n")
        if s.get("scoring_rationale"):
            w(f"**Why this score:** {s['scoring_rationale']}\n")
        if s.get("strengths"):
            w("**Strengths observed:**\n")
            for x in s["strengths"]:
                w(f"- {x}")
            w("")
    w("---\n")

    w("## 6. Priority queue — every critical and high finding\n")
    w(f"{sc['critical']} critical + {sc['high']} high findings. Full detail for these and all "
      f"{len(issues)} findings — observed evidence, impact, recommended fix — is in\n"
      "**[EXPERT_REVIEW_ISSUES.md](EXPERT_REVIEW_ISSUES.md)**; machine-readable data in\n"
      "[`expert_review_findings.json`](expert_review_findings.json). One further high-severity defect,\n"
      "[ZB-120](#zb-120), was found while auditing this record and is documented in §9.\n")
    w("| ID | Sev | Issue | Lens | Effort | Verified |")
    w("|---|---|---|---|---|---|")
    for f in issues:
        if f["severity"] not in ("critical", "high"):
            continue
        t = f["title"].replace("|", "/")
        v = f["verification"] if f["verification"] in ("CONFIRMED", "REFUTED") else "not verified"
        w(f"| [{f['id']}](EXPERT_REVIEW_ISSUES.md#{f['id'].lower()}) | {SEV_LABEL[f['severity']]} | {t} | "
          f"`{f['lens']}` | {f.get('effort') or '—'} | {v} |")
    w("")
    w(f"Medium and low findings ({sc['medium']} + {sc['low']}) are documented in the same register.\n")
    w("---\n")

    w(FINAL_ASSESSMENT.format(mean=stats["mean"], n=stats["n_lenses"], rubric_total=R["total"]))
    w(LIMITATIONS.format(verified=len(verified), serious=len(serious), confirmed=confirmed,
                         refuted=refuted, unverified=unverified, medlow=medlow,
                         mean=stats["mean"], commit=a["commit"]))
    w("*Provenance: generated by `pipeline/gen_expert_review.py` from "
      "[`expert_review_findings.json`](expert_review_findings.json) — the agents' returned results, "
      "archived verbatim. Full register: [EXPERT_REVIEW_ISSUES.md](EXPERT_REVIEW_ISSUES.md).*\n")
    OUT_MD.write_text("\n".join(o) + "\n", encoding="utf-8")

    # ---- register ----
    r = []
    rw = r.append
    rw("# Expert Panel Review — full issue register\n")
    rw(f"All **{len(issues)} findings** from the 15-lens expert panel on commit `{a['commit']}`, most\n"
       "severe first, each with a stable ID so it can be tracked and fixed individually.\n"
       f"`Verification` is the independent second-agent verdict; that pass covered {len(verified)} of the\n"
       f"{len(serious)} critical/high findings (capped at four per lens — ZB-044 was missed) and no\n"
       "medium/low findings. See [EXPERT_REVIEW.md](EXPERT_REVIEW.md) for the process, scores and\n"
       "overall assessment, and §9 there for [ZB-120](EXPERT_REVIEW.md#zb-120), found later.\n")
    rw(f"**Counts:** {sc['critical']} critical · {sc['high']} high · {sc['medium']} medium · {sc['low']} low\n")
    rw("---\n")
    cur = None
    for f in issues:
        if f["severity"] != cur:
            cur = f["severity"]
            rw(f"## {SEV_LABEL[cur]} severity\n")
        rw(f'<a id="{f["id"].lower()}"></a>\n')
        rw(f"### {f['id']} · {f['title']}\n")
        meta = [f"**Lens:** `{f['lens']}`", f"**Severity:** {SEV_LABEL[f['severity']]}"]
        if f.get("effort"):
            meta.append(f"**Effort:** {f['effort']}")
        meta.append(f"**Verification:** {f['verification']}")
        rw(" · ".join(meta) + "\n")
        rw(f"- **Where:** {f['location']}")
        rw(f"- **Observed:** {f['evidence']}")
        rw(f"- **Impact:** {f['impact']}")
        rw(f"- **Recommended fix:** {f['recommendation']}")
        if f.get("verification_note"):
            rw(f"- **Verifier's note:** {f['verification_note']}")
        rw("")
    OUT_ISSUES.write_text("\n".join(r) + "\n", encoding="utf-8")

    print(f"WROTE {OUT_MD.name} ({OUT_MD.stat().st_size // 1024}KB) · "
          f"{OUT_ISSUES.name} ({OUT_ISSUES.stat().st_size // 1024}KB)")
    print(f"issues={len(issues)} serious={len(serious)} verified={len(verified)} "
          f"(confirmed={confirmed} refuted={refuted}) unverified={unverified}")


def main() -> None:
    if "--from-raw" in sys.argv:
        raw = Path(sys.argv[sys.argv.index("--from-raw") + 1])
        archive = build_archive(raw)
        ARCHIVE.write_text(json.dumps(archive, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"WROTE {ARCHIVE.name} ({ARCHIVE.stat().st_size // 1024}KB) from raw output")
    else:
        archive = json.loads(ARCHIVE.read_text(encoding="utf-8"))
    render(archive)


if __name__ == "__main__":
    main()
