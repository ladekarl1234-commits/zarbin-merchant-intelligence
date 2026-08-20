"""The AI response contract — one structured object per AI-supported answer.

Every field is traceable and feeds both the UI and the Control Center AI-Ops view.
Numbers live in `evidence` (deterministic); `answer_fa` only ever rephrases them.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime


@dataclass
class AIResponse:
    answer_fa: str                       # final text shown to the user
    intent: str                          # deterministic intent chosen by the planner
    evidence: list[dict] = field(default_factory=list)  # metric evidence payloads
    confidence: str = "medium"           # "high" | "medium" | "low"
    source: str = "deterministic"        # "deterministic" | "llm" (llm = LLM rephrased)
    grounded: bool = True                # answer's numbers all come from evidence
    fallback: bool = False               # LLM was attempted but we used deterministic text
    quality_flags: list[str] = field(default_factory=list)  # e.g. ["no_evidence","hallucination_risk"]
    provider: str | None = None
    model: str | None = None
    latency_ms: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None
    note_fa: str = ""
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))

    def to_dict(self) -> dict:
        return asdict(self)
