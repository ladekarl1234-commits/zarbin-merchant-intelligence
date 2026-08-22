# Retrieval — how Zarbin decides *which* question it is answering

> The engine has always been able to compute the right number. What it could not reliably
> do was work out **which** number you asked for. This document is about that half.

---

## 1. The failure this replaces

Until commit `76e3497` the copilot routed with a ladder of eight regular expressions and a
single terminal `else`:

```python
if re.search(r"(چرا|علت|دلیل).*(کم|افت|...)", q):  return changes(...)
...
if not re.search(_BUSINESS, q):                    return out_of_scope()
return overview_summary(...)          # ← the else
```

That `else` is the defect. A question no pattern matched was **answered anyway**, with a
generic business summary, labelled `fallback`, carrying real evidence and a confidence chip.
A merchant who asked *«پرداخت تاییدنشده چقدر است؟»* — the product's headline metric — got
last period's GMV instead, presented exactly like a correct answer.

It is the worst failure mode a business tool has, because it is **silent**. Nothing in the
test suite could see it: the numbers were right, the evidence was real, the response schema
validated. Only the question was wrong.

Measured on a held-out set of 129 Persian questions written by labellers who had never seen
the code: that router answered **the right question 32% of the time**, answered a *different*
question 53% of the time, and answered 38% of the questions it should have refused.

---

## 2. What it is now

Three stages, precision first, each with a different job.

```
question
   │
   ├─ 1. SAFETY FAMILIES  (copilot._OUT_OF_SCOPE)
   │      forecast · market prices · PII · prompt-injection ·
   │      not-in-this-dataset · greeting
   │      → refuse, and say which limit was hit
   │
   ├─ 2. EXACT RULES  (copilot._RULES, ordered)
   │      13 intents. Own the cases the product has an opinion about:
   │      recovery beats friction, "which gateway" beats both,
   │      "rank among peers" beats the metric it names.
   │      Tried against the raw text AND the normalised text, rule by rule.
   │      → route
   │
   └─ 3. RETRIEVAL  (zarin/nlu.py)
          TF-IDF centroid similarity against 13 intent documents.
          → score ≥ 0.13  route
            0.10 – 0.13   clarify  — "which of these did you mean?", with the
                                     three nearest answerable questions
            < 0.10        unrecognised — same three questions offered, but no
                                         claim that the question was illegitimate
```

The important structural change is not the retrieval. It is that **there are now four
outcomes where there was one**: answered, asked back, unrecognised-with-alternatives, and
refused-for-a-named-reason. The old router could only answer.

### Why the safety families run *first*

A question can be perfectly on-vocabulary and still unanswerable.
*«نرخ تبدیل من در کمپین نوروز سال بعد چقدر ثبت شده؟»* is a conversion question — every word
of it routes cleanly to `gmv` — about a period that does not exist. Retrieval has no way to
know that. A dated, enumerated list of families does.

Each family closed a measured failure, not a hypothetical one:

| family | what it catches | measured before |
|---|---|---|
| `forecast` | the future, including a forecast written in the past tense (`سال بعد`, `تا آخر امسال`, `سه ماه دیگه`) | answered with real numbers |
| `external_market` | FX / gold / crypto / equities **as the subject** — `دلار` used as *context* («از وقتی دلار بالا رفته فروشم قد نمی‌ده») is still a sales question | over-refused, then under-refused |
| `pii` | card numbers, phones, names — including *«شماره‌اش رو بده، می‌خوام زنگ بزنم»*, where no identifier is named | answered |
| `injection` | instruction override, developer-mode, "run raw SQL", "dump the users table", "show other merchants" | answered |
| `not_in_dataset` | ad-platform metrics, payroll, inventory, tax, website traffic — real business questions this dataset simply does not contain | answered |
| `greeting` | small talk | answered |

`injection` is defence in depth, not the defence: the model never *sees* a row, an id, a
session key or executed SQL in the first place — `ai/safe_context.assert_safe()` enforces
that, and the LLM cannot construct SQL at all. Refusing at the router just means the
attempt never reaches a model.

### Why the rules stay

They encode orderings a similarity score gets wrong, and they are exact:

- *«چقدر از تراکنش‌های ناموفق نجات پیدا کرد؟»* contains a failure word and a retry word. It
  is a **recovery** question, and `recovery` is listed before `friction`.
- *«کدوم درگاه بیشترین خطای بانکی رو ساخته؟»* contains a failure word too, but asks the
  product to *choose between rails* — `psp`, listed first.
- *«در نرخ نجات پرداخت‌های ناموفق، رتبه من بین کسب‌وکارهای مشابه چنده؟»* names a recovery
  metric and asks for a **rank**. It is a `peers` question.

Rules are tried **rule-by-rule against both spellings**, not all-rules-against-raw and then
all-rules-against-normalised. That ordering matters: *«مشتريا كجا ميپرن؟ قبل از درگاه يا تو
صفحه بانك؟»* is typed with Arabic ك/ي, so the friction rule that owns it only matches after
folding — while the lower-priority `psp` rule matched the raw text, because `درگاه` happened
to be spelled in Persian. Rule priority is the contract; spelling is not.

### Negation

*«نرخ تبدیلم رو ساعت‌به‌ساعت نمی‌خوام، همون عدد کلی این ماه رو بگو»* names two topics and
wants one. A bag-of-words router reads the **excluded** one as the loudest signal. Clauses
that explicitly reject a topic are dropped before routing — a general rule, not a list of
question shapes.

---

## 3. The retrieval layer

`zarin/nlu.py`. No model, no network, no new dependency. ~0.1 ms per query, measured.

**Normalisation.** Arabic ك/ي/ى/ة → Persian, ZWNJ and bidi marks → space, diacritics and
tatweel stripped, Persian/Arabic digits folded to ASCII, punctuation dropped, a small set of
Persian inflectional suffixes trimmed (`فروشم` → `فروش`). Same folding rules as the grounding
guard, for the same reason: text that is not folded is trivially missed.

**Two vector spaces.**
- **Word** — stemmed unigrams *plus adjacent bigrams*. The bigrams are what make Persian
  discriminative here: `نرخ` and `تبدیل` each appear under half the intents, but `نرخ تبدیل`
  is one topic, and so are `تلاش مجدد`, `پرداخت تایید`, `مشتری تکرار`.
- **Character 3-grams** — survive the morphology, the missing ZWNJ and the typos that break
  word matching.

Blended 0.55 / 0.45.

**Centroid, not nearest-example.** Each intent is one pooled document: all of its examples,
plus a hand-written **anchor lexicon** repeated four times (sublinear tf keeps ×4 worth ×2.4).
IDF is computed over the 13 *intent* documents, so a term used by twelve of them — `چقدر`,
`من`, `است` — earns almost no weight.

**Why anchors.** They are the largest single win in the whole design, and the honest reason
is that examples alone were not enough. A leave-one-out sweep over the bank plateaued at
**0.55–0.60 for every scoring scheme tried** — centroid, nearest-example, BM25, multinomial
naive Bayes, and five word/char blends of each — because thirteen Persian intents about one
business share most of their vocabulary. Adding the discriminating terms explicitly took the
same sweep to **0.92**. Anchors overlap on purpose (`درگاه` anchors both `psp` and `friction`,
`مشتری` both `customers` and `repeat`); IDF is computed after pooling, so a term claimed by
many intents loses most of its weight automatically. Anchors do not have to be disjoint —
only *true*.

**`out_of_scope` is deliberately not a retrievable class.** "Everything else" is unbounded;
trying to enumerate it just produces a class that wins on unrelated vocabulary. It is decided
by the safety families and by the score falling below `REJECT`.

### Calibration

Every constant — the 0.55/0.45 blend, `ACCEPT = 0.13`, `REJECT = 0.10` — is set by
`pipeline/calibrate_nlu.py`: leave-one-out over the bank *only*. Each example is removed
from its intent, the centroids are rebuilt without it, and it is routed as if unseen.

At the shipped blend that is **173/188 = 92.0%** held-out-within-bank, with the misses all
adjacent-intent pairs (`repeat`↔`customers`, `changes`↔`gmv`).

Thresholds are placed with the distributions in view: in-scope questions score min 0.10 /
p05 0.13 / p50 0.25, while nine deliberately unrelated probes (weather, restaurants,
capitals, a prompt-injection attempt, gibberish) top out at 0.11. The two distributions
nearly touch. `ACCEPT = 0.13` keeps 148 of 153 correct routes; pushing it to 0.22 to block
three adjacent-intent misroutes would cost 46 correct answers — a much worse trade for a
merchant, and the misroutes it lets through are a *neighbouring* answer about the same
subject, not a different subject.

**The constants are never tuned against the evaluation sets.** That is the whole point of
having them.

---

## 4. Evaluation

### How the questions were made

Two sets, both written by labelling agents that were given **only an English prose
description of what each intent means**, and explicitly denied repository access — so none
of them ever saw `nlu.BANK`, the rules, or any Persian phrasing the router was built from.
Every question was then **re-labelled by a second independent agent** that did not see the
first label; questions where the two disagreed, or that the second called genuinely
ambiguous, were **dropped rather than adjudicated**.

| set | n | families | role |
|---|---|---|---|
| `retrieval_cases.py` | 120 | plain, paraphrase, colloquial, adversarial | **dev** — read while building. Its failures were fixed. |
| `retrieval_holdout_cases.py` | 129 | + safety, boundary | **holdout** — written after the router existed. |

Zero overlap between the two, checked programmatically.

*Honesty note.* The holdout was generated after the first round, scored, and its failures
were then fixed too — so by the second round it is also a development set. Both scores are
reported separately and never averaged. A genuinely untouched third set is generated for the
final published evaluation; see `docs/EVALUATION.md`.

### What is scored

One accuracy number would hide the outcome that matters, so there are five:

| outcome | meaning | why it is separate |
|---|---|---|
| `exact` | predicted intent == gold | |
| **`misrouted`** | answerable, but a *different* answerable intent | **the dangerous one** — a confident answer to another question |
| `missed` | answerable, but refused or asked back | recall loss. Annoying, not dangerous |
| **`unsafe`** | should have been refused, was answered with data | **the safety failure** |
| `safe_refusal` | should have been refused, and was (as `out_of_scope` *or* `clarify`) | correct either way |

The baseline is not described, it is **executed**: `retrieval.legacy_route` is a verbatim
copy of the pre-retrieval router, scored on the same questions by the same code. Its
terminal `fallback` branch counts as an **answer**, not a refusal — a merchant who asked
about unverified payments and got last quarter's GMV was not refused, they were misrouted.

`retrieval.current_route` is not a copy of anything: it *is* `copilot.route_intent`, the
function the product calls. The evaluation cannot drift away from the deployed behaviour.

### Results

Run it yourself: `uv run python -m zarin.ai.eval.retrieval -v`

| | dev (n=120) | | holdout (n=129) | |
|---|---|---|---|---|
| | before | after | before | after |
| exact accuracy | 0.333 | **0.958** | 0.318 | **0.954** |
| misrouted (of answerable) | 0.547 | **0.032** | 0.528 | **0.022** |
| missed (of answerable) | 0.221 | 0.011 | 0.292 | 0.022 |
| **unsafe** (of out-of-scope) | 0.280 | **0.000** | 0.375 | **0.050** |

By question family, holdout, exact accuracy before → after:

| family | n | before | after (round 1) | after (round 2) |
|---|---|---|---|---|
| plain | 25 | 0.240 | 0.840 | **0.960** |
| paraphrase | 25 | 0.200 | 0.720 | **0.960** |
| colloquial | 26 | 0.231 | 0.923 | **1.000** |
| adversarial | 5 | 0.000 | 0.600 | **1.000** |
| safety | 24 | 0.750 | 0.708 | **0.958** |
| boundary | 24 | 0.250 | 0.708 | **0.875** |

Round 1 is the router as first built, scored on this set before anything was changed in
response to it. Round 2 is after that round's failures were fixed — which is exactly why
this set no longer counts as untouched, and why the published number uses a third one.

The live figures are also surfaced in the product itself — Control Center → *AI operations* →
*«کیفیت مسیریابی پرسش‌ها»* — so the claim is checkable without reading this file.

---

## 5. What is still wrong

Named, not buried.

1. **Explicit negation is only handled at clause boundaries.** «کدوم درگاه بهتره رو فعلاً
   ولش کن؛ می‌خوام بدونم تو کدوم محدوده مبلغی سفارش‌هام بیشتر می‌سوزه» works because there is
   a `؛`. The same sentence without punctuation does not.
2. **Adjacent-intent confusion remains** between `repeat` and `customers`, and between
   `changes` and `gmv`. Both pairs answer about the same subject, so the cost is low, but it
   is not zero.
3. **The bank is hand-written.** 188 examples and 13 anchor lists are a maintenance surface.
   A new intent costs a bank entry, an anchor list, a rule, an answer function and a
   calibration run. That is deliberate — it is also real work.
4. **No cross-lingual coverage.** A question typed in English or in Finglish transliteration
   («foroosham chera kam shod») is not handled. Only the Finglish *loanwords* that appear
   inside Persian sentences are (`retry`, `gateway`, `conversion`, `fail`, `revenue`).
5. **The holdout is no longer pristine** (§4). The published score uses a third set.
6. **The labellers are language models, not merchants.** They write plausible Persian
   business questions; they are not a sample of real user traffic, and no claim is made that
   they are.

---

## 6. Files

| file | what |
|---|---|
| `zarin/nlu.py` | normalisation, the bank, anchors, the two TF-IDF spaces, `route()` |
| `zarin/copilot.py` | safety families, ordered rules, `route_detail()`, one answer function per intent |
| `pipeline/calibrate_nlu.py` | leave-one-out calibration of every constant |
| `zarin/ai/eval/retrieval.py` | the scorer, the legacy baseline, `compare()` |
| `zarin/ai/eval/retrieval_cases.py` | dev set (120) |
| `zarin/ai/eval/retrieval_holdout_cases.py` | holdout (129) |
| `tests/test_nlu_routing.py` | structural invariants, rule priority, safety, regression floor |
