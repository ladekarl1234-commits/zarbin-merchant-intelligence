"""Calibration set for the grounding guard's thresholds.

An adversarial verifier's standing objection to the guard was that `_NOVEL_RATIO`,
`_SENT_NOVEL_RATIO` and `_LEN_FACTOR` are "unvalidated magic numbers on a correctness
boundary with no calibration set". This file IS that calibration set: every attack below
is a string that provably evaded a previous version of the guard, and every faithful case
is a rephrasing the guard must NOT reject (a guard that rejects everything is not safe,
it just silently turns the LLM path off).

Both directions must hold. Changing a threshold without re-running this is not allowed.
"""
import pytest

from zarin.ai import gateway
from zarin.fa import fa_money, fa_num, fa_pct

DET = (f"نرخ تبدیل شما در این دوره {fa_pct(0.35)} است و "
       f"{fa_money(61_800_000_000)} پرداخت تاییدنشده دارید.")
# A deterministic text that ALREADY contains an imperative — nearly every real card's
# action_fa does. This is what turned the old membership test into a blanket licence.
DET_WITH_ACTION = f"نرخ تبدیل شما {fa_pct(0.35)} است. لاگ خطای درگاه را بررسی کنید."

# (label, deterministic text, llm text) — each one passed some earlier build of the guard.
ATTACKS = [
    ("invented cause, marker",        DET, DET + " چون درگاه بانک خراب است"),
    ("invented cause, colon form",    DET, DET + " علت اصلی: خرابی درگاه بانک."),
    ("invented cause, zwnj+diacritic", DET, DET[:-1] + "، به‌علتِ خرابی درگاه بانک، افت کرد."),
    ("invented advice, colon form",   DET, DET + " راهکار: تعویض درگاه بانک."),
    ("invented advice, bare verb",    DET, DET + " درگاه را عوض کن."),
    ("invented advice, impersonal",   DET, DET + " لازم است درگاه عوض شود."),
    ("invented advice, arabic script", DET, DET + " درگاه را عوض كنيد."),
    ("negation, first person",        DET, DET + " و هیچ مشکلی نداریم."),
    ("negation, passive",             DET, DET + " قابل بازیابی نمی‌شود."),
    ("negation, prepositional",       DET, DET + " بدون هیچ مشکلی تسویه شده."),
    ("negation, q-and-a",             DET, DET + " آیا مشکلی هست؟ خیر."),
    ("negation flip",                 DET, f"نرخ تبدیل شما {fa_pct(0.35)} نیست"),
    # The one that needs no evasion at all: a legitimate «کنید» in the deterministic text
    # used to unlock unlimited invented imperatives for the whole answer.
    ("marker unlock via real action", DET_WITH_ACTION,
     DET_WITH_ACTION + " همچنین درگاه را عوض کنید و تبلیغات را قطع کنید."),
]

# Numerically exact, semantically identical restatements. These must pass.
_D1 = f"فروش موفق {fa_money(61_800_000_000)} از {fa_num(23801)} پرداخت بود"
FAITHFUL = [
    ("reordered clauses", _D1,
     f"در این بازه {fa_num(23801)} پرداخت موفق داشتید و مجموع آن {fa_money(61_800_000_000)} شد"),
    ("hedged restatement", _D1, f"حدود {fa_money(61_800_000_000)} از {fa_num(23801)} پرداخت موفق داشتی"),
    ("shortened", _D1, f"{fa_money(61_800_000_000)} فروش موفق داشتید"),
    ("verbatim", _D1, _D1),
    ("rounded within tolerance", _D1, f"نزدیک به {fa_money(61_800_000_000)} فروش موفق"),
    ("imperative already in source", DET_WITH_ACTION,
     f"نرخ تبدیل شما {fa_pct(0.35)} است؛ لاگ خطای درگاه را بررسی کنید."),
]


# Written by an adversarial verifier BEFORE seeing the implementation, not by its author. This
# distinction is the point: the FAITHFUL list above was authored against the code, so it structurally
# cannot detect over-rejection — a guard tuned until its own examples pass will always pass them.
# These are the externally-authored controls. They are recorded as currently-REJECTED, i.e. as known
# false positives, because that is the honest state: over-rejection is safe (the deterministic text
# is returned) but it degrades the LLM path, which is exactly the ZB-004 failure mode.
KNOWN_OVER_REJECTIONS = [
    ("percent restated as a fraction of a hundred", DET,
     (f"در این بازه، از هر صد پرداخت ۳۵ مورد موفق بوده و مبلغ {fa_money(61_800_000_000)} "
      "هنوز تایید نشده باقی مانده است.")),
    ("synonym-heavy restatement", DET,
     (f"تبدیل شما {fa_pct(0.35)} ثبت شده؛ همچنین {fa_money(61_800_000_000)} تراکنش "
      "بدون تایید مانده است.")),
]


@pytest.mark.parametrize("label,det,llm", ATTACKS, ids=[a[0] for a in ATTACKS])
def test_guard_rejects_every_known_evasion(label, det, llm):
    assert gateway.grounding_failure(llm, det) is not None, label


@pytest.mark.parametrize("label,det,llm", KNOWN_OVER_REJECTIONS,
                         ids=[k[0] for k in KNOWN_OVER_REJECTIONS])
def test_known_false_positives_are_recorded_not_hidden(label, det, llm):
    """These SHOULD pass and currently do not. The assertion is inverted deliberately: if a future
    change makes one of them pass, this test fails and the entry must be promoted into FAITHFUL —
    which is how the known-defect list stays honest instead of quietly going stale."""
    assert gateway.grounding_failure(llm, det) is not None, (
        f"{label} now passes — move it from KNOWN_OVER_REJECTIONS into FAITHFUL")


@pytest.mark.parametrize("label,det,llm", FAITHFUL, ids=[f[0] for f in FAITHFUL])
def test_guard_accepts_faithful_rephrasings(label, det, llm):
    assert gateway.grounding_failure(llm, det) is None, label


def test_normalisation_folds_arabic_and_zwnj_variants():
    """The folding is what makes the marker check un-evadable by spelling, so pin it directly."""
    assert gateway._norm("كنيد") == gateway._norm("کنید")
    assert gateway._norm("به‌دلیل").replace(" ", "") == gateway._norm("به دلیل").replace(" ", "")
    assert gateway._norm("به‌علتِ").replace(" ", "") == "بهعلت"
