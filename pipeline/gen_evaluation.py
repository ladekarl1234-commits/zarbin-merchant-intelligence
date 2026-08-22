"""Generate docs/EVALUATION.md from docs/evaluation_rounds.json.

Two modes, mirroring pipeline/gen_expert_review.py:

    python pipeline/gen_evaluation.py
        Regenerate the document from the committed archive. Reproducible from the repo alone.

    python pipeline/gen_evaluation.py --add-round <workflow-output.json> --round <n> \
        --commit <sha> [--label "<short label>"]
        Import one panel run into the archive, then regenerate.

The archive is the source of truth; every table below is derived from it. Prose that is not
derivable from the data (the assessment, the limitations) lives in this file and is clearly
labelled as hand-written, so a reader can tell which sentences a machine produced and which
a person did.
"""
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "docs" / "evaluation_rounds.json"
OUT = ROOT / "docs" / "EVALUATION.md"

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
    "retrieval-eval": "Retrieval quality & evaluation methodology",
    "testing-qa": "Testing & quality assurance",
}
ORDER = ["rubric-official", "architecture", "code-quality", "data-correctness", "statistics",
         "security", "reliability", "scalability", "product", "business", "ux", "design",
         "accessibility", "ai-grounding", "retrieval-eval", "testing-qa"]


def _load() -> dict:
    return json.loads(ARCHIVE.read_text(encoding="utf-8")) if ARCHIVE.exists() else {"rounds": []}


def _rubric_from(round_data: dict) -> dict | None:
    """Parse `A=<n>/90 C=<n>/75 D=<n>/60 U=<n>/45 T=<n>/30 TOTAL=<n>/300` out of the
    rubric lens's summary. Returns None when the lens did not report in that form —
    better an absent table than an invented one."""
    lens = next((L for L in round_data.get("lenses", []) if L.get("lens") == "rubric-official"), None)
    if not lens:
        return None
    if isinstance(lens.get("rubric"), dict):
        return lens["rubric"]
    text = (lens.get("summary") or "") + " " + (lens.get("not_higher_because") or "")
    out = {}
    for key, field, mx in (("A", "actionability", 90), ("C", "correctness", 75),
                           ("D", "depth", 60), ("U", "ux", 45), ("T", "technical", 30),
                           ("TOTAL", "total", 300)):
        tag = f"{key}="
        i = text.find(tag)
        if i < 0:
            return None
        num = text[i + len(tag):].split("/")[0].strip()
        try:
            out[field] = int(float(num))
        except ValueError:
            return None
        out[f"{field}_max"] = mx
    return out


def _delta(a, b, digits=1):
    if a is None or b is None:
        return "—"
    d = round(b - a, digits)
    return f"{d:+.{digits}f}" if d else "0.0"


def _sev_counts(round_data: dict) -> dict:
    return round_data.get("finding_counts") or {}


def render(archive: dict) -> str:
    rounds = sorted(archive.get("rounds", []), key=lambda r: r["round"])
    if not rounds:
        return "# Evaluation\n\n_No rounds recorded._\n"
    first, last = rounds[0], rounds[-1]
    L = []
    A = L.append

    A("# Independent evaluation — before and after")
    A("")
    A("> Machine-generated from `docs/evaluation_rounds.json` by `pipeline/gen_evaluation.py`.")
    A("> Every number below comes from the archive; the two clearly-labelled prose sections at")
    A("> the end are hand-written.")
    A("")

    # ---- headline
    A("## Headline")
    A("")
    A("| | " + " | ".join(f"Round {r['round']}" + (f" — {r['label']}" if r.get("label") else "")
                           for r in rounds) + " | change |")
    A("|---" * (len(rounds) + 2) + "|")
    A("| Commit | " + " | ".join(f"`{r.get('commit','?')}`" for r in rounds) + " | |")
    A("| Date | " + " | ".join(r.get("date", "?") for r in rounds) + " | |")
    A("| Lenses | " + " | ".join(str(len(r.get("lenses", []))) for r in rounds) + " | |")
    A("| **Mean dimension score** | " + " | ".join(f"**{r.get('mean_score','?')}** / 100" for r in rounds)
      + f" | **{_delta(first.get('mean_score'), last.get('mean_score'))}** |")
    rub = [_rubric_from(r) for r in rounds]
    if all(rub):
        A("| **Competition rubric** | " + " | ".join(f"**{x['total']}** / 300" for x in rub)
          + f" | **{_delta(rub[0]['total'], rub[-1]['total'], 0)}** |")
    fc = [_sev_counts(r) for r in rounds]
    A("| Findings raised | " + " | ".join(str(x.get("total", "?")) for x in fc) + " | |")
    A("| — critical / high | " + " | ".join(f"{x.get('critical','?')} / {x.get('high','?')}" for x in fc) + " | |")
    A("| Critical+high confirmed after adversarial re-check | "
      + " | ".join(str(len((r.get("verification") or {}).get("confirmed", []))) for r in rounds) + " | |")
    A("| — refuted | " + " | ".join(str(len((r.get("verification") or {}).get("refuted", []))) for r in rounds) + " | |")
    A("")

    # ---- rubric detail
    if all(rub):
        A("## The competition rubric, criterion by criterion")
        A("")
        A("| Criterion | Max | " + " | ".join(f"R{r['round']}" for r in rounds) + " | change |")
        A("|---|---:|" + "---:|" * (len(rounds) + 1))
        for field, label in (("actionability", "Actionability & novelty of insights"),
                             ("correctness", "Correctness & traceability"),
                             ("depth", "Analytical depth"),
                             ("ux", "Non-technical UX"),
                             ("technical", "Technical quality & executability")):
            A(f"| {label} | {rub[0][field + '_max']} | "
              + " | ".join(str(x[field]) for x in rub)
              + f" | {_delta(rub[0][field], rub[-1][field], 0)} |")
        A("| **Total** | **300** | " + " | ".join(f"**{x['total']}**" for x in rub)
          + f" | **{_delta(rub[0]['total'], rub[-1]['total'], 0)}** |")
        A("")

    # ---- per-lens
    A("## Dimension scores")
    A("")
    A("| Lens | Dimension | " + " | ".join(f"R{r['round']}" for r in rounds) + " | change | confidence (last) |")
    A("|---|---|" + "---:|" * (len(rounds) + 1) + "---|")
    by_round = [{L_["lens"]: L_ for L_ in r.get("lenses", [])} for r in rounds]
    for key in ORDER:
        if not any(key in br for br in by_round):
            continue
        cells = [str(br[key]["score"]) if key in br else "—" for br in by_round]
        a = by_round[0].get(key, {}).get("score")
        b = by_round[-1].get(key, {}).get("score")
        conf = by_round[-1].get(key, {}).get("confidence", "—")
        A(f"| `{key}` | {LENS_TITLE.get(key, key)} | " + " | ".join(cells)
          + f" | {_delta(a, b, 0)} | {conf} |")
    A("")

    # ---- what each lens said, last round
    A(f"## What each expert concluded (round {last['round']})")
    A("")
    for key in ORDER:
        lens = by_round[-1].get(key)
        if not lens:
            continue
        A(f"### {LENS_TITLE.get(key, key)} — {lens['score']}/100")
        A("")
        A(f"*Lens `{key}` · confidence {lens.get('confidence','?')}*")
        A("")
        A(lens.get("summary", "").strip())
        A("")
        if lens.get("not_higher_because"):
            A(f"**Not higher because:** {lens['not_higher_because'].strip()}")
            A("")
        if lens.get("not_lower_because"):
            A(f"**Not lower because:** {lens['not_lower_because'].strip()}")
            A("")
        strengths = lens.get("verified_strengths") or []
        if strengths:
            A("**Independently verified strengths:**")
            A("")
            for s in strengths:
                A(f"- {s}")
            A("")

    # ---- confirmed findings, per round
    for r in rounds:
        confirmed = (r.get("verification") or {}).get("confirmed", [])
        if not confirmed:
            continue
        A(f"## Round {r['round']} — critical/high findings that survived adversarial re-check")
        A("")
        A("Each was raised by one lens, then handed to a separate agent whose brief was to")
        A("**refute** it. Only findings that agent could reproduce appear here.")
        A("")
        A("| # | Sev | Lens | Finding | Location |")
        A("|---|---|---|---|---|")
        for i, c in enumerate(confirmed, 1):
            title = (c.get("title") or "").replace("|", "\\|")
            loc = (c.get("location") or "").replace("|", "\\|")
            A(f"| {i} | {c.get('severity','?')} | `{c.get('lens','?')}` | {title} | `{loc}` |")
        A("")
        refuted = (r.get("verification") or {}).get("refuted", [])
        if refuted:
            A(f"<details><summary>{len(refuted)} claims the verifier refuted</summary>")
            A("")
            for x in refuted:
                A(f"- **{(x.get('title') or '').replace('|', '')}** (`{x.get('lens','?')}`) — {x.get('why','')}")
            A("")
            A("</details>")
            A("")

    # ---- hand-written sections
    A("---")
    A("")
    A(HAND_WRITTEN_METHOD)
    A("")
    A(HAND_WRITTEN_LIMITS)
    A("")
    A(f"<sub>Generated {datetime.now(UTC).strftime('%Y-%m-%d')} by `pipeline/gen_evaluation.py`.</sub>")
    return "\n".join(L) + "\n"


HAND_WRITTEN_METHOD = """## Method (hand-written)

Each round is one run of `pipeline/panel.js` through the Workflow orchestrator:

1. **Judge.** Sixteen expert lenses run *in parallel and in isolation* — no lens sees another
   lens's output, so their agreements are independent rather than anchored. Each is given the
   repository, a live deployment to probe, the commands to run it, and the product's own
   claims, and is told to assume the product is worse than it looks. Each returns a score in
   0–100 with an explicit *not higher because / not lower because*, and up to ten findings,
   each needing a location and reproducible evidence.
2. **Verify.** Every `critical` and `high` finding is handed to a **separate** agent whose
   brief is to **refute** it, defaulting to refuted when it cannot be reproduced. Only
   findings that survive are recorded. This is the step that keeps a panel of language models
   from grading on plausibility.

The two rounds are the same panel definition run against two commits, so the comparison is
like-for-like. The round-2 lenses were not shown round-1's scores."""

HAND_WRITTEN_LIMITS = """## What this evaluation is not (hand-written)

- **The panel is language models, not people.** They read code, run commands and probe a live
  deployment, which makes their findings checkable — every one carries a location and a
  command. It does not make their *scores* calibrated against human experts. Treat the
  deltas as more meaningful than the absolute numbers.
- **No human usability testing.** UX, design and accessibility are assessed from source,
  computed contrast ratios and rendered output. No Persian-speaking merchant was observed
  using the product.
- **The rubric lens is inside the mean.** It scores the same product against a different
  instrument, so it is partly correlated with the other fifteen.
- **A round-2 lens judges a product that was changed in response to round 1.** That is the
  point, but it also means round 2 is not an independent second opinion of round 1 — it is a
  re-measurement after targeted repair, and some of the repair was aimed at exactly what
  round 1 measured.
- **Scores move with panel composition.** A different set of sixteen lenses would land a few
  points either way."""


def main() -> None:
    archive = _load()
    if "--add-round" in sys.argv:
        raw = Path(sys.argv[sys.argv.index("--add-round") + 1])
        n = int(sys.argv[sys.argv.index("--round") + 1])
        commit = sys.argv[sys.argv.index("--commit") + 1]
        label = sys.argv[sys.argv.index("--label") + 1] if "--label" in sys.argv else ""
        payload = json.loads(raw.read_text(encoding="utf-8"))
        payload = payload.get("result", payload)
        payload["round"] = n
        payload["commit"] = commit
        payload["label"] = label
        payload["date"] = datetime.now(UTC).strftime("%Y-%m-%d")
        archive["rounds"] = [r for r in archive.get("rounds", []) if r["round"] != n] + [payload]
        ARCHIVE.write_text(json.dumps(archive, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"archived round {n} ({len(payload.get('lenses', []))} lenses) -> {ARCHIVE}")
    OUT.write_text(render(archive), encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
