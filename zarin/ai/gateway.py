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

# Map Persian/Arabic digits to ASCII, and the Persian decimal mark ٫ (U+066B) to ".".
_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩٫", "01234567890123456789.")
# Strip ONLY thousands groupers between digits: ASCII comma, Persian comma (U+060C),
# Arabic thousands (U+066C), and whitespace. The DECIMAL mark is deliberately preserved, so
# "۲٫۳" stays "2.3" (≠ "23") — conflating them would let an LLM turn 2.3% into 23% and pass.
_THOUSANDS = re.compile(r"(?<=\d)[,،٬\s](?=\d)")

# Persian scale words, longest first so "هزار میلیارد" wins over "هزار" (ZB-038: an abbreviation
# is only legitimate if its scale word restores the original magnitude — "۶۱۸ میلیارد" is NOT
# "۶۱٫۸ میلیارد", and string-prefix matching used to accept exactly that).
_SCALE = (("هزار میلیارد", 1e12), ("میلیارد", 1e9), ("میلیون", 1e6), ("هزار", 1e3))
# Unit families. A number only traces to a deterministic number of the SAME family, so the same
# digits carrying a different unit (rial vs percent vs transactions) can no longer pass (ZB-039).
# NOTE: تومان is its own family — 1 تومان = 10 ریال, so treating them as one family let the model
# restate a rial figure as toman (a silent 10x error) and still "trace" (ZB-039).
_UNITS = (("ریال", "irr"), ("تومان", "toman"), ("درصد", "pct"), ("٪", "pct"), ("%", "pct"),
          ("واحد", "pp"), ("مشتری", "count"), ("پرداخت", "count"), ("تراکنش", "count"),
          ("جلسه", "count"), ("تلاش", "count"), ("روز", "day"), ("ساعت", "hour"))
# --- normalisation -------------------------------------------------------------------
# Persian text has several ways to spell the same word, and a matcher that does not fold them
# is trivially evaded: Arabic ك/ي for Persian ک/ی, an optional ZWNJ inside compounds
# («به‌دلیل» vs «به دلیل»), and optional diacritics («به‌علتِ»). Both sides of every textual
# comparison below go through _norm first.
_AR_FOLD = str.maketrans({
    "ك": "ک",   # ARABIC KAF   -> PERSIAN KEHEH
    "ي": "ی",   # ARABIC YEH   -> FARSI YEH
    "ى": "ی",   # ALEF MAKSURA -> FARSI YEH
    "ة": "ه",   # TEH MARBUTA  -> HEH
    # ZWNJ and the bidi marks are INVISIBLE, so they are written as chr() rather than as
    # literals: a literal is unreviewable in a diff, and the bidi marks in particular are
    # the Trojan-Source class ruff flags as PLE2502.
    chr(0x200C): " ",   # ZERO WIDTH NON-JOINER  («به دلیل» spelled as one token)
    chr(0x200F): " ",   # RIGHT-TO-LEFT MARK
    chr(0x200E): " ",   # LEFT-TO-RIGHT MARK
})
# harakat (U+064B..U+0652), superscript alef, tatweel
_DIACRITICS = re.compile("[" + "".join(chr(c) for c in [*range(0x64B, 0x653), 0x670, 0x640]) + "]")


def _norm(text: str) -> str:
    return _DIACRITICS.sub("", text.translate(_AR_FOLD))


# Words that assert something the engine did not: a cause, an instruction, or a negation. A short
# insertion like «چون درگاه خراب است» copies almost every other word, so a bag-of-words novelty
# ratio cannot see it, and it has no sentence boundary for the containment check below to catch —
# this is the check that closes intra-sentence ZB-004.
#
# Compared by COUNT, not membership. Membership was a hole with a normal trigger: nearly every
# card's action_fa ends in «کنید», and one legitimate occurrence in the deterministic text used to
# license unlimited invented imperatives across the whole answer.
# Whitespace is stripped from both markers and text before matching, so «به دلیل» and «به‌دلیل»
# are one pattern rather than two spellings to enumerate.
_ASSERTION_MARKERS = tuple(m.replace(" ", "") for m in (
    "چون", "زیرا", "به دلیل", "بخاطر", "به خاطر", "باعث", "علت", "دلیل", "ناشی از", "منجر به",
    "کنید", "بکنید", "پیشنهاد می کنم", "توصیه می کنم", "بهتر است", "لازم است", "راهکار", "راه حل",
    "باید", "نیست", "نبوده", "نشده است", "ندارد", "نداریم", "ندارید", "خیر"))
# NOT markers: «هیچ» and «بدون» are ordinary Persian function words, not negations — budgeting them
# rejected faithful rephrasings («... تراکنش بدون تایید مانده است»). The sentences they appeared in
# during round 2 are still caught, by sentence containment rather than by vocabulary.
_SENT_SPLIT = re.compile(r"[.!?؟؛:\n]+")
# Function words carry no claim, so they neither prove containment nor count as invention.
_STOP = frozenset([
    "در", "این", "از", "به", "با", "را", "که", "و", "تا", "هم", "یا", "بر", "هر", "یک", "آن",
    "ما", "شما", "است", "بود", "بوده", "شد", "شده", "می", "ها", "های", "برای", "نیز", "باشد",
    "دارد", "دارید", "داشتی", "داشتید", "هست", "کرد", "کرده", "طی", "حدود", "یعنی", "او",
    "خود", "تو", "اید", "ای", "رو",
])
# Numbers, scale words and unit words are the NUMERIC check's job (_values/_traces above, which
# compare magnitudes, not spellings). Re-judging them as prose is what made the guard reject
# «۶۱٫۸ میلیارد ریال» as a restatement of a bare «۶۱٬۸۰۰٬۰۰۰٬۰۰۰» — same fact, different surface.
_NUMERIC_WORDS = frozenset([w for w, _ in _SCALE] + [w for w, _ in _UNITS])
_HAS_DIGIT = re.compile(r"[0-9٠-٩۰-۹]")
_TOKEN_SPLIT = re.compile(r"[\s،؛,()«»\"'؟?!]+")
# A sentence the deterministic text does not support is an insertion, whatever words it uses —
# this is the half of the check that does NOT depend on enumerating vocabulary.
# Thresholds are pinned by tests/test_grounding_calibration.py; do not tune them without it.
_SENT_NOVEL_RATIO = 0.5
_SENT_NOVEL_MIN = 3       # partly-copied sentence: needs real substance to count as invention
_SENT_ALL_NOVEL_MIN = 2   # a sentence with NOTHING from the engine needs far less


def _content_words(text: str) -> list[str]:
    """Prose tokens only — the words that can carry a claim."""
    return [w for w in _TOKEN_SPLIT.split(text)
            if len(w) > 1 and w not in _STOP and w not in _NUMERIC_WORDS
            and not _HAS_DIGIT.search(w)]


def _unsupported_sentence(llm_norm: str, det_norm: str) -> bool:
    """True if some sentence of the LLM text stands on its own — i.e. its content words are
    mostly (or entirely) absent from the deterministic text. Catches invented causes, advice
    and negations regardless of the words chosen, which a blacklist cannot."""
    det_words = set(_content_words(det_norm))
    for sentence in _SENT_SPLIT.split(llm_norm):
        content = _content_words(sentence)
        if not content:
            continue
        novel = [w for w in content if w not in det_words]
        if not novel:
            continue
        if len(novel) == len(content) and len(novel) >= _SENT_ALL_NOVEL_MIN:
            return True     # nothing in this sentence came from the engine
        if len(novel) >= _SENT_NOVEL_MIN and len(novel) / len(content) > _SENT_NOVEL_RATIO:
            return True
    return False
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
# Content the model must never introduce: an answer about payments has no business containing a
# link, an email or a phone number — those are classic injected/hallucinated payloads (ZB-020).
_FORBIDDEN = re.compile(r"https?://|www\.|\S+@\S+\.\S+|\[[^\]]*\]\([^)]*\)|\+?\d[\d\-\s]{9,}\d")
_WORD_RE = re.compile(r"[^\W\d_]{4,}", re.UNICODE)
# Small bare integers are list/ordinal noise ("۳ اولویت اول"), not claims; larger ones are claims.
_BARE_INT_IGNORE = 12
_REL_TOL = 0.01          # a restatement may round (۶۱٫۸۴۷ → ۶۱٫۸), not invent
_LEN_FACTOR = 1.6        # a "rephrase" that is much longer than the source is adding content
# Novelty is a coarse backstop only. It was set at 0.6, which rejected faithful Persian
# rephrasings (the LLM path silently degraded to a no-op); the assertion-marker check above is
# what carries the safety, so this can be loose enough to let a genuine restatement through.
_NOVEL_RATIO = 0.85
_NOVEL_MIN = 8


def _values(text: str) -> list[tuple[str, float]]:
    """Extract (unit_family, value) pairs, resolving Persian scale words to real magnitudes."""
    # _norm FIRST. This was the one comparison that skipped it, and skipping it defeated the whole
    # numeric layer: «ميليارد ريال» in Arabic script matched neither _SCALE nor _UNITS, so the
    # number lost both its scale and its unit — and an empty unit traces to ANY family. That let
    # «نرخ تبدیل شما ۳۵ ميليارد ريال است» pass against a deterministic «۳۵ درصد»: a conversion
    # rate republished as 35 billion rial. The same sentence in Persian script was correctly
    # rejected, which is what proves this was a normalisation gap and not a tolerance one.
    t = _THOUSANDS.sub("", _norm(text).translate(_PERSIAN_DIGITS))
    out: list[tuple[str, float]] = []
    for m in _NUM_RE.finditer(t):
        val = float(m.group())
        tail = t[m.end():m.end() + 24]
        head = t[max(0, m.start() - 2):m.start()]
        mult = 1.0
        for word, factor in _SCALE:
            if word in tail[:len(word) + 2]:
                mult = factor
                break
        unit = ""
        for word, fam in _UNITS:
            if word in tail[:len(word) + 18] or word in head:
                unit = fam
                break
        if not unit and mult == 1.0 and val.is_integer() and val <= _BARE_INT_IGNORE:
            continue      # ordinal / list marker, not a quantitative claim
        out.append((unit, val * mult))
    return out


def _traces(unit: str, val: float, det: list[tuple[str, float]]) -> bool:
    for d_unit, d_val in det:
        if unit and d_unit and unit != d_unit:
            continue      # same digits, different unit → not the same fact
        hi = max(abs(val), abs(d_val)) or 1.0
        if abs(val - d_val) / hi <= _REL_TOL:
            return True
    return False


def grounding_failure(llm_text: str, deterministic_text: str) -> str | None:
    """Return the reason the LLM text is NOT an acceptable rephrasing, or None if it is.

    The guard used to inspect digits only, so invented causality, invented advice, injected links
    and unit swaps all passed as "grounded" (ZB-004/ZB-020/ZB-038/ZB-039). It now checks four
    things: forbidden payloads, length inflation, numeric value+unit tracing, and novel content.
    """
    if _FORBIDDEN.search(llm_text):
        return "forbidden_content"
    if len(llm_text) > max(120, len(deterministic_text) * _LEN_FACTOR):
        return "length_inflation"
    det_vals = _values(deterministic_text)
    for unit, val in _values(llm_text):
        if not _traces(unit, val, det_vals):
            return "ungrounded_number"
    # A cause, an instruction or a negation the engine never asserted. Two complementary checks:
    # markers catch insertions INSIDE a copied sentence (no boundary for the next check to see),
    # sentence containment catches appended sentences whatever vocabulary they use.
    llm_norm, det_norm = _norm(llm_text), _norm(deterministic_text)
    llm_tight, det_tight = llm_norm.replace(" ", ""), det_norm.replace(" ", "")
    for marker in _ASSERTION_MARKERS:
        if llm_tight.count(marker) > det_tight.count(marker):
            return "unsupported_assertion"
    if _unsupported_sentence(llm_norm, det_norm):
        return "unsupported_assertion"
    det_words = {w for w in _WORD_RE.findall(deterministic_text)}
    novel = [w for w in _WORD_RE.findall(llm_text) if w not in det_words]
    total = len(_WORD_RE.findall(llm_text)) or 1
    if len(novel) >= _NOVEL_MIN and len(novel) / total > _NOVEL_RATIO:
        return "novel_content"    # wholesale invention, not a rephrasing
    return None


def is_grounded(llm_text: str, deterministic_text: str) -> bool:
    """True iff the LLM text is an acceptable rephrasing of the deterministic answer."""
    return grounding_failure(llm_text, deterministic_text) is None


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
    except Exception as e:  # noqa: BLE001 — a misbehaving provider must never break the copilot
        base.fallback = True
        base.quality_flags = ["provider_error"]
        base.provider = getattr(provider, "name", None)
        _emit(base, merchant_scope, surface, success=False, grounded=False, err=str(e))
        return base

    reason = grounding_failure(comp.text, deterministic_answer_fa)
    if reason:
        # LLM introduced unsupported content → discard its text, keep the truth
        base.fallback = True
        base.grounded = True  # the answer we RETURN is the deterministic (grounded) one
        base.quality_flags = ["hallucination_risk", f"reason:{reason}"]
        base.provider, base.model = comp.provider, comp.model
        base.latency_ms, base.total_tokens = comp.latency_ms, comp.total_tokens
        base.cost_usd = comp.cost_usd
        # telemetry records the LLM output as NOT grounded (that is the real signal),
        # even though the answer we show is the grounded deterministic one.
        _emit(base, merchant_scope, surface, success=False, grounded=False)
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


def _emit(r: AIResponse, merchant_scope: str, surface: str, *, success: bool,
          grounded: bool | None = None, err: str | None = None) -> None:
    # `grounded` here is the LLM OUTPUT's grounding (the real quality signal), which differs
    # from r.grounded (whether the SHOWN answer is grounded — true by construction on fallback).
    flags = list(r.quality_flags)
    if not r.evidence and "no_evidence" not in flags:
        flags.append("no_evidence")
    if err:
        flags.append(f"error:{err[:80]}")
    telemetry.record(
        intent=r.intent, source=r.source,
        grounded=r.grounded if grounded is None else grounded, fallback=r.fallback,
        success=success, provider=r.provider, model=r.model, latency_ms=r.latency_ms,
        prompt_tokens=r.prompt_tokens, completion_tokens=r.completion_tokens,
        total_tokens=r.total_tokens, cost_usd=r.cost_usd, evidence_count=len(r.evidence),
        quality_flags=flags, merchant_scope=merchant_scope, surface=surface,
    )
