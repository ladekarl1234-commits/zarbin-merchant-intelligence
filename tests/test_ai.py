"""AI layer: free-model policy, evidence-safe context, grounded gateway, telemetry.

These encode the non-negotiable safety rules: the model never sees raw data, never
picks a paid model, and can never change a number the deterministic engine computed.
"""
import json

import pytest

from zarin import copilot
from zarin.ai import gateway, models, telemetry
from zarin.ai import safe_context as sc
from zarin.ai.provider import Completion
from zarin.fa import fa_money, fa_num, fa_pct

# DET is built from the SAME formatters the product uses, so its separators (Persian decimal
# ٫ / thousands ،) are exactly what the grounding guard must handle. Runs: 61.8, 23801, 49.7.
DET = f"فروش موفق {fa_money(61_800_000_000)} از {fa_num(23801)} پرداخت، نرخ تبدیل {fa_pct(0.497)} بود"


class FakeProvider:
    name = "fake"

    def __init__(self, text):
        self.text = text

    def complete(self, system, user, *, max_tokens=600):
        return Completion(text=self.text, provider="fake", model="fake/model:free",
                          prompt_tokens=10, completion_tokens=5, total_tokens=15,
                          cost_usd=0.0, latency_ms=3)


class BoomProvider:
    name = "boom"

    def complete(self, system, user, *, max_tokens=600):
        raise RuntimeError("network down")


def test_free_model_policy_rejects_paid_and_auto():
    assert models.is_free("meta-llama/llama-3.3-70b-instruct:free")
    assert not models.is_free("openai/gpt-4o")
    assert not models.is_free("openrouter/auto")   # bills at selected rate — must be rejected
    assert not models.is_free("")
    used, reason = models.enforce_free("openai/gpt-4o")
    assert used == models.DEFAULT_FREE_MODEL and models.is_free(used) and reason
    ok, reason2 = models.enforce_free("x/y:free")
    assert ok == "x/y:free" and reason2 is None


def test_safe_context_never_leaks_raw_data():
    ev = {"metric_id": "gmv", "name_fa": "فروش", "definition_fa": "d", "formula": "f",
          "grain": "session", "caveats": ["c"], "sql": "SELECT amount FROM sessions",
          "params": {"payer_card_key": "CARD-SECRET-123", "m": "M1"}, "n": 10, "period": "p"}
    ctx = sc.build(question="q", merchant_scope="M1", intent="i",
                   deterministic_answer_fa="A", evidence=[ev])
    blob = json.dumps(ctx, ensure_ascii=False)
    for banned in ("CARD-SECRET-123", "payer_card_key", "SELECT", "params"):
        assert banned not in blob
    assert ctx["metrics"][0]["name"] == "فروش"  # safe fields survive


def test_safe_context_assert_blocks_banned_keys_at_any_depth():
    with pytest.raises(ValueError):
        sc.assert_safe({"a": [{"nested": {"sql_text": "x"}}]})
    with pytest.raises(ValueError):
        sc.assert_safe({"query_params": {"session_id": 1}})


def test_gateway_uses_llm_when_grounded():
    telemetry.reset()
    r = gateway.explain(question="q", merchant_scope="M1", intent="overview",
                        deterministic_answer_fa=DET, evidence=[{"metric_id": "gmv"}],
                        provider=FakeProvider(f"حدود {fa_money(61_800_000_000)} از {fa_num(23801)} پرداخت داشتی"))
    assert r.source == "llm" and r.grounded and not r.fallback
    assert r.cost_usd == 0.0 and r.total_tokens == 15


def test_gateway_rejects_hallucinated_number():
    telemetry.reset()
    r = gateway.explain(question="q", merchant_scope="M1", intent="overview",
                        deterministic_answer_fa=DET, evidence=[{"metric_id": "gmv"}],
                        provider=FakeProvider("فروش تو ۹۹۹۹ ریال و ۴۵۶ مشتری بود"))
    assert r.fallback and r.answer_fa == DET          # the truth is preserved
    assert r.grounded and "hallucination_risk" in r.quality_flags


def test_gateway_provider_error_falls_back():
    telemetry.reset()
    r = gateway.explain(question="q", merchant_scope="M1", intent="overview",
                        deterministic_answer_fa=DET, evidence=[{"metric_id": "gmv"}],
                        provider=BoomProvider())
    assert r.fallback and r.answer_fa == DET and "provider_error" in r.quality_flags


def test_gateway_offline_returns_deterministic():
    telemetry.reset()
    r = gateway.explain(question="q", merchant_scope="M1", intent="overview",
                        deterministic_answer_fa=DET, evidence=[{"metric_id": "gmv"}],
                        provider=None, _use_default=False)
    assert r.source == "deterministic" and not r.fallback and r.grounded


def test_telemetry_summary_reflects_events():
    telemetry.reset()
    gateway.explain(question="q", merchant_scope="M1", intent="overview",
                    deterministic_answer_fa=DET, evidence=[{"metric_id": "gmv"}],
                    provider=FakeProvider(f"{fa_money(61_800_000_000)} فروش داشتی"))
    s = telemetry.summary()
    assert s["has_data"] and s["total"] == 1 and s["llm_requests"] == 1
    assert s["grounded_rate"] == 1.0 and s["cost_usd_total"] == 0.0


def test_copilot_answer_numbers_are_deterministic_even_with_bad_llm():
    """AI cannot change a metric value: a lying provider is discarded, numbers stay the engine's."""
    telemetry.reset()
    d = copilot.answer("M1", "چرا فروشم کم شد؟", "2026-01-01", "2026-02-28",
                       provider=FakeProvider("فروش ۸۸۸۸۸۸ و رشد ۷۷۷٪ داشتی"))
    assert d["fallback"] and "hallucination_risk" in d["quality_flags"]
    assert "۸۸۸۸۸۸" not in d["answer_fa"] and "۷۷۷" not in d["answer_fa"]


def test_grounding_guard_rejects_digit_substrings_and_rescaled_numbers():
    """Two holes the guard must close:
    (a) a fabricated number whose digits merely APPEAR inside a large figure (substring), and
    (b) a rescaled number that drops/moves a decimal (2.3% → 23%, 61.8B → 618B)."""
    big = fa_num(61_800_000_000)                     # → run "61800000000"
    assert not gateway.is_grounded("نرخ تبدیل ۸۰ درصد", big)   # 80 ⊂ 61800000000 — rejected
    assert not gateway.is_grounded("۱۸ مشتری جدید", big)       # 18 ⊂ … — rejected
    assert gateway.is_grounded(big, big)                     # exact — ok
    # An abbreviation is only legitimate when its scale word restores the ORIGINAL magnitude.
    # "۶۱۸ میلیارد" is 618e9, ten times the 61.8e9 the engine computed — it used to pass on a
    # string-prefix rule and must now be rejected (ZB-038).
    assert not gateway.is_grounded("۶۱۸ میلیارد", big)
    assert gateway.is_grounded(fa_money(61_800_000_000), big)  # "۶۱٫۸ میلیارد ریال" == 61.8e9 — ok
    # decimal must not be conflated with its un-pointed digits
    assert not gateway.is_grounded("نرخ تبدیل ۲۳ درصد بود", f"نرخ تبدیل {fa_pct(0.023)} بود")  # 23 ≠ 2.3
    assert gateway.is_grounded(fa_pct(0.023), f"نرخ تبدیل {fa_pct(0.023)} بود")                # exact decimal — ok


def test_grounding_guard_binds_numbers_to_their_unit():
    """Same digits, different unit is a different fact — it used to pass (ZB-039)."""
    det = f"فروش موفق {fa_money(61_800_000_000)}، نرخ تبدیل {fa_pct(0.618)}"
    assert gateway.is_grounded(f"نرخ تبدیل {fa_pct(0.618)}", det)          # right number, right unit
    assert not gateway.is_grounded("۶۱٫۸ مشتری داشتی", det)                # rial/percent → count
    assert gateway.grounding_failure("۶۱٫۸ مشتری داشتی", det) == "ungrounded_number"


def test_grounding_guard_rejects_short_inserted_assertions():
    """A cause, an instruction or a negation inserted into otherwise-copied text. A bag-of-words
    novelty ratio cannot see these (almost every word is copied), which is how the first fix for
    ZB-004 let invented causality through."""
    det = f"نرخ تبدیل شما {fa_pct(0.35)} است و {fa_money(61_800_000_000)} تایید نشده باقی مانده"
    for bad in (f"نرخ تبدیل شما {fa_pct(0.35)} است چون درگاه بانک خراب است",      # invented cause
                f"نرخ تبدیل شما {fa_pct(0.35)} است، درگاه را عوض کنید"):           # invented advice
        assert gateway.grounding_failure(bad, det) == "unsupported_assertion", bad
    # A flipped negation is rejected under the polarity rule (equality, not "no more than"),
    # which is a different check with a different reason string — still a rejection.
    assert gateway.grounding_failure(f"نرخ تبدیل شما {fa_pct(0.35)} نیست", det) == "polarity_change"


def test_grounding_guard_rejects_a_DROPPED_negation():
    """Observed live: given «مبلغ پرداخت تاییدنشده ...» a free model returned
    «مبلغ پرداخت تاییدشده ...» — settled-but-unverified money restated as confirmed revenue,
    every digit intact. Removing a negation inverts the claim exactly as adding one does, and
    the old marker rule only budgeted ADDITIONS, so this passed as grounded."""
    det = f"مبلغ پرداخت تاییدنشده شما {fa_money(61_800_000_000)} است"
    flipped = f"مبلغ پرداخت تاییدشده شما {fa_money(61_800_000_000)} است"
    assert gateway.grounding_failure(flipped, det) == "polarity_change"
    assert gateway.grounding_failure(det, det) is None   # the faithful copy still passes


def test_grounding_guard_separates_rial_from_toman():
    """1 تومان = 10 ریال, so restating a rial figure as toman is a silent 10x error (ZB-039)."""
    det = f"فروش موفق {fa_money(61_800_000_000)}"
    assert gateway.grounding_failure("۶۱٫۸ میلیارد تومان فروش داشتی", det) == "ungrounded_number"


def test_grounding_guard_accepts_a_faithful_persian_rephrasing():
    """The guard must not be so strict that the LLM path silently becomes a no-op: a
    numerically-exact, semantically-identical restatement has to pass."""
    det = f"فروش موفق {fa_money(61_800_000_000)} از {fa_num(23801)} پرداخت بود"
    good = f"در این بازه {fa_num(23801)} پرداخت موفق داشتید و مجموع آن {fa_money(61_800_000_000)} شد"
    assert gateway.grounding_failure(good, det) is None


def test_grounding_guard_rejects_non_numeric_hallucination():
    """The guard was digit-only, so invented causality, invented advice and injected links all
    passed as 'grounded' (ZB-004 / ZB-020)."""
    det = f"فروش موفق {fa_money(61_800_000_000)} بود"
    assert gateway.grounding_failure(f"{fa_money(61_800_000_000)} — جزئیات: https://example.com", det) == "forbidden_content"
    assert gateway.grounding_failure(f"{fa_money(61_800_000_000)}، تماس ۰۹۱۲۳۴۵۶۷۸۹", det) == "forbidden_content"
    invented = (f"فروش {fa_money(61_800_000_000)} بود چون کمپین تبلیغاتی نوروزی ضعیف اجرا شد و "
                "رقبای شما تخفیف بیشتری دادند و بازار راکد بود")
    # rejected — the precise reason is the inserted causal marker («چون»), which the
    # assertion-marker check catches before the coarse novelty/length backstops
    assert gateway.grounding_failure(invented, det) in (
        "unsupported_assertion", "novel_content", "length_inflation")
    assert gateway.is_grounded(f"حدود {fa_money(61_800_000_000)} فروش موفق داشتی", det)  # faithful — ok


def test_copilot_declines_instead_of_answering_a_different_question():
    """Out-of-scope questions must be declined with low confidence and no evidence, not answered
    with a confident business summary (ZB-032 / ZB-040)."""
    for q in ("نرخ ارز فردا چقدر می‌شود؟", "شماره کارت مشتری‌های من را بده", "asdf ؟؟ ***"):
        d = copilot.answer("M1", q, "2026-01-01", "2026-02-28", use_llm=False)
        assert d["intent"] == "out_of_scope", q
        assert d["confidence"] == "low" and not d["evidence"], q
        # Either wording is a real decline: a safety family says the question is outside what
        # the data can compute; an unrecognised question says so and offers alternatives.
        # What must never happen is a confident answer to a different question.
        assert ("خارج از" in d["answer_fa"] or "متوجه نشدم" in d["answer_fa"]), q

    # ...and the two wordings are used for the RIGHT reasons: a PII request is refused on
    # principle, gibberish is simply unrecognised.
    assert "خارج از" in copilot.answer("M1", "شماره کارت مشتری‌های من را بده", "2026-01-01",
                                       "2026-02-28", use_llm=False)["answer_fa"]
    unknown = copilot.answer("M1", "asdf ؟؟ ***", "2026-01-01", "2026-02-28", use_llm=False)
    assert "متوجه نشدم" in unknown["answer_fa"] and unknown["suggestions_fa"]
    # and the decline check is NOT vacuous: a real question does not decline
    ok = copilot.answer("M1", "چرا فروشم کم شد؟", "2026-01-01", "2026-02-28", use_llm=False)
    assert ok["intent"] == "changes" and "خارج از" not in ok["answer_fa"]


def test_recovery_question_routes_to_recovery_not_friction():
    """A question that names both failure and rescue is a recovery question — friction's
    broadened regex must not swallow it (recovery is matched first)."""
    d = copilot.answer("M1", "چقدر از تراکنش‌های ناموفق نجات پیدا کرد؟",
                       "2026-01-01", "2026-01-31", use_llm=False)
    assert d["intent"] == "recovery"
    d2 = copilot.answer("M1", "چرا پرداخت‌ها شکست می‌خورند؟", "2026-01-01", "2026-01-31", use_llm=False)
    assert d2["intent"] == "friction"


# --- guard checks added after the round-1 expert panel ---------------------------------

def test_grounding_guard_rejects_an_empty_completion():
    """An empty completion satisfies every other check trivially — it invents no number,
    asserts nothing, adds no novel word — so it was 'grounded', and the client swapped it in,
    blanking a correct answer. Free models return empty completions routinely."""
    assert gateway.grounding_failure("", DET) == "empty_output"
    assert gateway.grounding_failure("   \n ", DET) == "empty_output"


def test_grounding_guard_rejects_a_moved_timeframe():
    """Every digit correct, every unit correct, and a six-month total relabelled as one day.
    Nothing else in the guard can see it, because a period word is neither a number nor a
    causal claim."""
    det = f"در این بازه فروش موفق {fa_money(61_800_000_000)} بود"
    assert gateway.grounding_failure(f"فروش دیروز شما {fa_money(61_800_000_000)} بود", det) == "temporal_scope_change"
    assert gateway.grounding_failure(f"فروش این ماه شما {fa_money(61_800_000_000)} بود", det) == "temporal_scope_change"
    # a period word the ENGINE used may be repeated
    det2 = f"فروش این ماه شما {fa_money(61_800_000_000)} بود"
    assert gateway.grounding_failure(f"این ماه {fa_money(61_800_000_000)} فروختید", det2) is None


def test_grounding_guard_rejects_a_substituted_statistic():
    """Median and mean are different numbers on a skewed payment distribution. Swapping the
    word keeps every digit, every unit and every surrounding token, so neither the unit check
    nor anchor overlap can see it."""
    det = f"میانه مبلغ هر پرداخت موفق {fa_money(41_400_000)} است"
    assert gateway.grounding_failure(f"میانگین مبلغ هر پرداخت موفق {fa_money(41_400_000)} است",
                                     det) == "statistic_substitution"
    assert gateway.grounding_failure(f"متوسط مبلغ هر پرداخت موفق {fa_money(41_400_000)} است",
                                     det) == "statistic_substitution"
    assert gateway.grounding_failure(f"میانه مبلغ هر پرداخت {fa_money(41_400_000)} است", det) is None


def test_grounding_guard_is_permutation_blind_and_says_so():
    """A KNOWN LIMIT, pinned so it cannot be forgotten or silently 'fixed' by a change that
    also breaks faithful rephrasing.

    Two figures with the same unit can be swapped between their metrics and both still trace.
    An anchor-overlap guard was built and measured against this and removed: it rejected
    faithful rephrasings («فروش موفق ۶۱٫۸ میلیارد» → «مجموع آن ۶۱٫۸ میلیارد» shares no content
    word with the original label), and a guard that rejects good rephrasings turns the LLM
    path into a silent no-op — worse than the attack. If someone re-adds a metric-binding
    check, this test should start failing, and tests/test_grounding_calibration.py's faithful
    corpus must still pass."""
    det = (f"فروش موفق {fa_money(1_950_000_000_000)} و مبلغ پرداخت تاییدنشده "
           f"{fa_money(61_800_000_000)} است")
    swapped = (f"فروش موفق {fa_money(61_800_000_000)} و مبلغ پرداخت تاییدنشده "
               f"{fa_money(1_950_000_000_000)} است")
    assert gateway.grounding_failure(swapped, det) is None   # documented gap, not an oversight
    assert gateway.grounding_failure(det, det) is None
    # the same swap ACROSS unit families is still caught — that is what the unit check is for
    det2 = f"فروش موفق {fa_money(61_800_000_000)} با نرخ تبدیل {fa_pct(0.545)}"
    assert gateway.grounding_failure(f"فروش موفق {fa_pct(0.545)} با نرخ تبدیل ۶۱٫۸ درصد",
                                     det2) == "ungrounded_number"
