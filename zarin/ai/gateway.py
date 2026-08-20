"""AI gateway — turns a deterministic result into a grounded, optionally LLM-phrased answer.

Contract: the LLM may ONLY rephrase. A grounding guard rejects any answer that
introduces a number the deterministic engine did not compute; on rejection (or any
provider error, or no key) the deterministic Persian text is returned verbatim. The
numbers a merchant sees are therefore always the engine's, never the model's.
"""
from __future__ import annotations

import re

from . import telemetry
from .contract import AIResponse
from .provider import AIProvider, default_provider
from .safe_context import build as build_safe_context

_GROUNDING_NOTE = "این پاسخ بر پایه اعداد قطعیِ موتور تحلیلی است؛ مدل زبانی فقط آن را ساده‌تر بیان کرده است."
_DETERMINISTIC_NOTE = "این پاسخ مستقیماً از موتور تحلیلی قطعی می‌آید؛ همه اعداد قابل ردیابی‌اند."

_SYSTEM_PROMPT = (
    "تو دستیار «زرین‌بین» هستی. وظیفه‌ات فقط این است که یک تحلیل ازپیش‌محاسبه‌شده را به فارسیِ ساده و "
    "دوستانه بازنویسی کنی. قوانین قطعی:\n"
    "۱) هیچ عددی نساز. فقط از اعدادی استفاده کن که در computed_answer_fa آمده‌اند.\n"
    "۲) هیچ ادعای علّی جدیدی نکن که در متن محاسبه‌شده نیست.\n"
    "۳) اگر مطمئن نیستی، همان متن محاسبه‌شده را بازگو کن.\n"
    "۴) کوتاه، محترمانه و بدون اصطلاح فنی جواب بده. پاسخ فقط فارسی باشد."
)

_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def _digit_runs(text: str) -> list[str]:
    ascii_text = text.translate(_PERSIAN_DIGITS)
    # collapse thousands separators so 61,800 and 61800 compare equal
    ascii_text = re.sub(r"(?<=\d)[,٬.٬](?=\d)", "", ascii_text)
    return [r for r in re.findall(r"\d+", ascii_text) if len(r) >= 2]


def is_grounded(llm_text: str, deterministic_text: str) -> bool:
    """Every multi-digit number in the LLM answer must trace to the deterministic text."""
    det = _digit_runs(deterministic_text)
    for x in _digit_runs(llm_text):
        if not any(x in d or d in x for d in det):
            return False
    return True


def explain(*, question: str, merchant_scope: str, intent: str, deterministic_answer_fa: str,
            evidence: list[dict], confidence: str | None = None, surface: str = "merchant",
            provider: AIProvider | None = None, _use_default: bool = True) -> AIResponse:
    """Return a grounded AIResponse. Never raises for provider problems — it falls back."""
    if provider is None and _use_default:
        provider = default_provider()

    base = AIResponse(
        answer_fa=deterministic_answer_fa, intent=intent, evidence=evidence,
        confidence=confidence or "medium", source="deterministic", grounded=True,
        note_fa=_DETERMINISTIC_NOTE,
    )

    if provider is None:  # offline / no key — intended path, not a failure
        _emit(base, merchant_scope, surface, success=True)
        return base

    try:
        ctx = build_safe_context(
            question=question, merchant_scope=merchant_scope, intent=intent,
            deterministic_answer_fa=deterministic_answer_fa, evidence=evidence, confidence=confidence,
        )
        user = (
            "این تحلیل قطعی را به فارسیِ ساده بازنویسی کن. فقط از همین اعداد استفاده کن:\n\n"
            f"پرسش کاربر: {question}\n"
            f"تحلیل محاسبه‌شده: {ctx['computed_answer_fa']}\n"
            f"متریک‌ها: {', '.join(m['name'] for m in ctx['metrics'] if m.get('name'))}"
        )
        comp = provider.complete(_SYSTEM_PROMPT, user)
    except (ValueError, RuntimeError) as e:
        base.fallback = True
        base.quality_flags = ["provider_error"]
        base.provider = getattr(provider, "name", None)
        _emit(base, merchant_scope, surface, success=False, err=str(e))
        return base

    if not is_grounded(comp.text, deterministic_answer_fa):
        # LLM introduced an unsupported number → discard its text, keep the truth
        base.fallback = True
        base.grounded = True  # the answer we RETURN is the deterministic (grounded) one
        base.quality_flags = ["hallucination_risk"]
        base.provider, base.model = comp.provider, comp.model
        base.latency_ms, base.total_tokens = comp.latency_ms, comp.total_tokens
        base.cost_usd = comp.cost_usd
        _emit(base, merchant_scope, surface, success=False)
        return base

    out = AIResponse(
        answer_fa=comp.text, intent=intent, evidence=evidence,
        confidence=confidence or "medium", source="llm",
        grounded=True, fallback=False, provider=comp.provider, model=comp.model,
        latency_ms=comp.latency_ms, prompt_tokens=comp.prompt_tokens,
        completion_tokens=comp.completion_tokens, total_tokens=comp.total_tokens,
        cost_usd=comp.cost_usd, note_fa=_GROUNDING_NOTE,
    )
    _emit(out, merchant_scope, surface, success=True)
    return out


def _emit(r: AIResponse, merchant_scope: str, surface: str, *, success: bool, err: str | None = None) -> None:
    flags = list(r.quality_flags)
    if not r.evidence and "no_evidence" not in flags:
        flags.append("no_evidence")
    if err:
        flags.append(f"error:{err[:80]}")
    telemetry.record(
        intent=r.intent, source=r.source, grounded=r.grounded, fallback=r.fallback,
        success=success, provider=r.provider, model=r.model, latency_ms=r.latency_ms,
        prompt_tokens=r.prompt_tokens, completion_tokens=r.completion_tokens,
        total_tokens=r.total_tokens, cost_usd=r.cost_usd, evidence_count=len(r.evidence),
        quality_flags=flags, merchant_scope=merchant_scope, surface=surface,
    )
