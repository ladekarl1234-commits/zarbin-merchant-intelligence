# Spec — 15-agent expert evaluation + auditable review record

## Request
Run a comprehensive review with 10–15 specialized expert agents covering technical architecture,
product quality, business viability, UX, security/reliability, data & analytics quality,
scalability/maintainability, operational readiness, overall software quality (+ any other serious
dimension). Score against the evaluation criteria from the original master prompt. Document every
issue so it can be systematically addressed afterwards. **Make the whole evaluation part of the
GitHub repository documentation** — a transparent, structured, auditable record: the process, the
~15 agents, the dimensions, the scores, key findings, identified issues, and the final assessment.

## Explicit exclusions (this round)
Demo video and deployment/hosting/release/CI-CD/infrastructure are **out of scope** — not scored,
no findings raised. Automated tests and code-level quality gates remain in scope.

## Grounding criteria (from the original master prompt, verbatim weights)
| Criterion | Points |
|---|---:|
| Actionability and novelty of insights | 90 |
| Correctness and traceability | 75 |
| Analytical depth | 60 |
| Nontechnical UX | 45 |
| Technical quality and executability | 30 |
| **Total** | **300** |

## Method
- 15 independent expert lenses, run in parallel as a workflow, each: inspects the real code and
  live behaviour (read-only), scores its dimension 0–100 with an explicit rationale, lists
  strengths, and documents findings (severity, location, evidence, impact, recommendation, effort).
- Every `critical`/`high` finding is then **independently verified** by a separate agent
  (CONFIRMED / REFUTED with cited evidence) before it enters the public record.
- Aggregates (mean/median/min/max, severity counts) computed deterministically from returned data —
  not estimated by a model.
- Agents are read-only: no file writes, no `npm run build`, no git writes, no server restarts.

## Acceptance criteria
1. 15 lenses complete; each has a score, rationale, strengths and findings.
2. Every critical/high finding carries a verification verdict.
3. `docs/EXPERT_REVIEW.md` records: process, panel roster, dimension scores, aggregate result,
   rubric mapping, the full issue register (each issue individually addressable), and an honest
   final assessment including limitations of the review itself.
4. README links the record; the repo therefore contains the reasoning, not just a score.
5. No fabricated numbers: every figure in the document traces to a returned agent result or a
   command that was actually run.

## Non-goals
Fixing the issues in this task (the register exists so they can be prioritised next); re-reviewing
video/deployment; changing product behaviour.
