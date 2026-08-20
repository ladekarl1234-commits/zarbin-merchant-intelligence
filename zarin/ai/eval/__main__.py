"""`uv run python -m zarin.ai.eval` — run the Copilot evaluation and print a report."""
from __future__ import annotations

import json

from .runner import run_eval


def main() -> None:
    rep = run_eval()
    ind = rep["indicators"]
    print(f"\nCopilot evaluation — merchant {rep['merchant']}  ({rep['passed']}/{rep['total']} cases passed)\n")
    print(f"  deterministic correctness : {_p(ind['deterministic_correctness'])}")
    print(f"  grounding quality         : {_p(ind['grounding_quality'])}")
    print(f"  refusal safety            : {_p(ind['refusal_safety'])}")
    print("  language quality          : (human judge — not auto-scored)")
    print("  business usefulness       : (human judge — not auto-scored)\n")
    for c in rep["cases"]:
        mark = "PASS" if c["passed"] else "FAIL"
        print(f"  [{mark}] {c['id']:<20} intent={c['intent']}/{c['expected_intent']} ev={c['evidence_count']}")
    print()
    # machine-readable tail for CI / Control Center ingestion
    print(json.dumps({"indicators": ind, "passed": rep["passed"], "total": rep["total"]}, ensure_ascii=False))


def _p(x: float | None) -> str:
    return "n/a" if x is None else f"{round(x*100)}%"


if __name__ == "__main__":
    main()
