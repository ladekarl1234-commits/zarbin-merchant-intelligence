# ADR-0002 — Deterministic analytics, LLM explains only

Status: Accepted · Date: 2026-08

## Context
An AI copilot answers business questions in Persian on both surfaces. The risk: an LLM that
invents numbers, causality, or customer behavior — plausible and wrong — on financial data.

## Decision
The **deterministic engine is the source of truth for every number.** The LLM may only
*rephrase* a pre-computed, traceable answer. The pipeline is fixed:

```
question → intent/analytical plan → deterministic tools → structured evidence
        → [optional] LLM explanation → grounding guard → final answer + AI response contract
```

`Source → LLM → insight` is **forbidden**. The LLM never sees SQL, never builds SQL, never
answers a numeric question from model memory.

## Enforcement
- `ai/gateway.py` **grounding guard**: extract the multi-digit numbers from the LLM text; every
  one must trace (substring, either direction, digit-normalized) to the deterministic answer.
  On any violation → discard the LLM text, return the deterministic text, flag `hallucination_risk`.
- No key / provider error / grounding failure → deterministic text verbatim (`fallback`).
- Merchant `copilot.py` and `ops_copilot.py` both produce the deterministic answer + evidence
  first; the gateway is a thin, optional rephrase layer.

## Consequences
- The copilot is correct and fully usable **offline** (no key, no network).
- AI quality is measurable (grounded rate, fallback rate, hallucination-risk, evidence coverage)
  and separated into deterministic-correctness / grounding / language / usefulness — never one score.
- Cost: the LLM sometimes falls back when it abbreviates numbers oddly; we prefer a safe fallback
  to an ungrounded answer.

## Rejected
- **LLM-first / RAG-over-rows** analytics — un-auditable, un-groundable on money. Rejected.
- **Function-calling with open SQL** — an LLM constructing SQL against payment data is a
  data-exfiltration and correctness risk. Only bounded deterministic tools are exposed.
