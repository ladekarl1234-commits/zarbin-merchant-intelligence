"""Persian intent retrieval — the copilot's understanding layer.

`copilot._plan` used to be a ladder of regexes: first pattern to match wins, and a
question no pattern matched got a generic business summary labelled `fallback`. That
is a *silent* retrieval failure — the merchant is answered, just not the question they
asked — and it was the single largest source of wrong answers in the product.

This module adds the recall half, without giving up the precision half:

  1. RULES   (still in copilot._plan) run first. They are exact and ordered, and they
             own the cases where the product has a strong opinion — e.g. a question
             containing both a failure word and a retry word is a *recovery* question.
  2. SEARCH  (here) runs only when no rule fired. It retrieves the nearest intent from
             a labelled bank of example questions and returns a score, so the caller can
             route confidently, ask for clarification, or decline — three outcomes where
             there used to be one.

How the search works — deliberately no model, no network, no new dependency:

  * every example and every incoming question is normalised (Arabic→Persian letters,
    ZWNJ and bidi marks removed, diacritics stripped, Persian digits folded, a small
    set of Persian inflectional suffixes trimmed);
  * two TF-IDF vector spaces are built over the bank at import: **word** unigrams, which
    carry topic, and **character 3-grams**, which survive the morphology, the missing
    ZWNJ and the typos that break word matching («فروشم» ↔ «فروش», «تاييد» ↔ «تایید»);
  * an intent's score is the cosine similarity of the question against that intent's
    *centroid* — its examples plus a small anchor lexicon pooled into one document —
    blended 55/45 between the two spaces.

Cost: 166 examples over 13 intents, both matrices built once at import (~15 ms), ~0.1 ms
per query (measured).
Deterministic: the same question always routes the same way — the same contract the
numbers have. Fully offline; the LLM is not involved in routing.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import pairwise

# --- normalisation -----------------------------------------------------------------
# Same folding rules as the grounding guard (ai/gateway.py): Persian text has several
# spellings for the same word and a matcher that does not fold them is trivially evaded
# — here, trivially *missed*.
_AR_FOLD = str.maketrans({
    "ك": "ک", "ي": "ی", "ى": "ی", "ة": "ه", "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا",
    "ؤ": "و", "ئ": "ی",
    chr(0x200C): " ",   # ZWNJ
    chr(0x200D): " ",   # ZWJ
    chr(0x200F): " ",   # RLM
    chr(0x200E): " ",   # LRM
})
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩٫", "01234567890123456789.")
_DIACRITICS = re.compile("[" + "".join(chr(c) for c in [*range(0x64B, 0x653), 0x670, 0x640]) + "]")
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_WS = re.compile(r"\s+")

# Persian inflectional endings, longest first. Trimmed only from tokens long enough to
# survive it, so «ها» (a word) and «مان» are not eaten out of short tokens.
_SUFFIXES = ("هایمان", "هایتان", "هایشان", "هایی", "هایم", "هایت", "هایش", "ها", "های",
             "ترین", "تر", "مان", "تان", "شان", "یم", "ید", "ند", "ام", "ات", "اش", "م", "ت", "ش")
_MIN_STEM = 4

# Function words carry no topic. Question words stay OUT of this list on purpose:
# «چرا» (why) genuinely separates a diagnosis question from a lookup question.
_STOP = frozenset(["و", "در", "به", "از", "با", "را", "که", "این", "آن", "یک", "هم", "یا", "بر", "تا", "هر", "نیز", "اگر", "ولی", "اما", "پس", "چون", "البته", "است", "بود", "باش", "شد", "شده", "شود", "می", "ای", "های", "ها", "برای", "روی", "مورد", "طور", "بین", "من", "ما", "شما", "او", "ایشان", "خود", "مال"])

_TOKEN = re.compile(r"[^\W\d_]+|\d+", re.UNICODE)


def normalize(text: str) -> str:
    t = (text or "").translate(_AR_FOLD).translate(_DIGITS)
    t = _DIACRITICS.sub("", t)
    t = _PUNCT.sub(" ", t)
    return _WS.sub(" ", t).strip().lower()


def _stem(w: str) -> str:
    for suf in _SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= _MIN_STEM:
            return w[: -len(suf)]
    return w


def tokens(text: str) -> list[str]:
    """Stemmed content unigrams plus adjacent bigrams.

    The bigrams are what make the word space discriminative in Persian: «نرخ» and «تبدیل»
    each appear under half the intents, but «نرخ تبدیل» is one topic, and «تلاش مجدد» /
    «پرداخت تایید» / «مشتری تکرار» are each worth more than either of their halves.
    """
    uni = [_stem(w) for w in _TOKEN.findall(normalize(text)) if w not in _STOP and len(w) > 1]
    return uni + [f"{a}_{b}" for a, b in pairwise(uni)]


def char_grams(text: str, n: int = 3) -> list[str]:
    s = " " + normalize(text) + " "
    return [s[i:i + n] for i in range(max(0, len(s) - n + 1))]


# --- the labelled bank -------------------------------------------------------------
# One entry per intent the deterministic engine can actually answer.
#
# `out_of_scope` is deliberately NOT a class here. "Everything else" is unbounded, so it
# cannot be retrieved — trying to enumerate it just produces a class that wins on unrelated
# vocabulary. Out-of-scope is decided two other ways: the high-precision families in
# copilot._OUT_OF_SCOPE (forecast, market prices, PII, greetings), and the REJECT threshold
# below, which is what catches the open-ended rest.
#
# These examples are the *training* side of the router. The evaluation set in
# zarin/ai/eval/retrieval_cases.py is written independently of this file, so a score
# against it measures generalisation rather than recall of these strings.
BANK: dict[str, tuple[str, ...]] = {
    "changes": (
        "چرا فروشم کم شد؟",
        "دلیل افت درآمدم چیست؟",
        "چه چیزی باعث شد فروش پایین بیاید؟",
        "فروشم نسبت به دوره قبل چه تغییری کرده؟",
        "چرا این ماه بدتر از ماه قبل بود؟",
        "درآمدم افت کرده، علتش چیست؟",
        "رشد فروشم از کجا آمده؟",
        "تغییر فروش من از تعداد جلسه بوده یا از نرخ تبدیل؟",
        "سهم هر عامل در تغییر درآمد چقدر است؟",
        "فروشم بالا رفته، چه چیزی عوض شده؟",
        "چرا پولم کمتر شده؟",
        "روند فروش من نزولی است یا صعودی؟",
        "تجزیه تغییر فروش را نشانم بده",
        "چرا درآمد این دوره با دوره قبل فرق دارد؟",
        "علت کاهش فروش من چیست؟",
        "فروش من چرا خراب شد؟",
        "مقایسه فروش این ماه با ماه گذشته",
        "چه اتفاقی برای درآمدم افتاد؟",
        "فروشم یهو بالا رفت، بخاطر تعداد مشتری بود یا مبلغ خرید؟",
        "فروشم این هفته یهو ریخت، چه شد؟",
        "فروشم پرید بالا، از کجا آمد؟ سبد خرید بزرگ‌تر شد یا آدم بیشتر آمد؟",
        "از وقتی اوضاع عوض شده فروشم قد نمی‌دهد، دقیقاً چه چیزی تغییر کرده؟",
    ),
    "hours": (
        "بهترین ساعت فروش کی است؟",
        "مشتری‌ها چه ساعتی بیشتر خرید می‌کنند؟",
        "در چه زمانی از روز پرداخت موفق بیشتر است؟",
        "کدام ساعت بدترین نرخ تبدیل روز را دارد؟",
        "توزیع ساعتی تراکنش‌های من چطور است؟",
        "شب بهتر می‌فروشم یا صبح؟",
        "پیک ساعتی خرید مشتریانم کی است؟",
        "چه ساعتی از روز تبلیغ بگذارم بهتر است؟",
        "ساعت شلوغ درگاه من کی است؟",
        "کدام ساعت روز ضعیف‌ترین است؟",
        "الگوی ساعتی خرید چیست؟",
        "بیشترین پرداخت در چه ساعتی ثبت شده؟",
    ),
    "recovery": (
        "چقدر تراکنش با تلاش مجدد نجات پیدا کرد؟",
        "نرخ بازیابی پرداخت‌های ناموفق چقدر است؟",
        "چقدر پول از retry برگشت؟",
        "چند نفر بعد از شکست اول دوباره پرداخت کردند؟",
        "ریکاوری پرداخت من چطور است؟",
        "از تلاش دوم چقدر فروش به دست آمد؟",
        "مبلغ نجات‌یافته با تلاش مجدد چقدر بوده؟",
        "چند جلسه بعد از خطای اول موفق شد؟",
        "تلاش مجدد چقدر برایم درآمد ساخت؟",
        "نجات پرداخت در کسب‌وکار من چقدر کار می‌کند؟",
        "بعد از ناموفق شدن، چند درصد دوباره تلاش می‌کنند؟",
        "recovery rate من چند است؟",
    ),
    "friction": (
        "چرا پرداخت‌ها شکست می‌خورند؟",
        "بیشترین دلیل ناموفق شدن تراکنش چیست؟",
        "کجای مسیر پرداخت مشتری را از دست می‌دهم؟",
        "نرخ خطای بانکی من چقدر است؟",
        "چند نفر قبل از رسیدن به درگاه منصرف می‌شوند؟",
        "مشتری‌ها در صفحه بانک رها می‌کنند؟",
        "قیف پرداخت من کجا نشتی دارد؟",
        "وضعیت شکست تراکنش‌ها چطور است؟",
        "چرا خرید نیمه‌کاره رها می‌ماند؟",
        "اصطکاک پرداخت من کجاست؟",
        "نرخ انصراف پیش از پرداخت چقدر است؟",
        "چند درصد تراکنش‌ها با خطای بانکی رد می‌شوند؟",
        "مراحل قیف پرداخت را نشانم بده",
        "کجا بیشترین ریزش را دارم؟",
        "درصد رهاشدن در بانک چقدر است؟",
        "چرا اینقدر تراکنش‌هایم fail می‌شود؟",
        "مشتری‌ها کجا می‌پرند، قبل از درگاه یا در صفحه بانک؟",
    ),
    "peers": (
        "نسبت به کسب‌وکارهای مشابه چطورم؟",
        "با رقبا مقایسه‌ام کن",
        "جایگاه من بین همتایان کجاست؟",
        "صدک من بین پذیرنده‌های مشابه چند است؟",
        "بقیه فروشگاه‌های هم‌رده من چه وضعی دارند؟",
        "بهتر از میانگین بازار هستم یا بدتر؟",
        "رتبه من در دسته‌بندی خودم چیست؟",
        "بنچمارک صنعت من چقدر است؟",
        "همتایان من چه عملکردی دارند؟",
        "در مقایسه با مشابه‌هایم کجا ضعیفم؟",
        "نسبت به بقیه چطور کار می‌کنم؟",
        "رقبای هم‌اندازه من بهترند؟",
    ),
    "repeat": (
        "مشتریان تکراری چند نفرند؟",
        "چقدر از فروشم از مشتری‌های برگشتی است؟",
        "مشتری وفادار دارم؟",
        "نرخ بازگشت مشتری من چقدر است؟",
        "ارزش مشتری‌های تکراری چقدر است؟",
        "چند درصد مشتری‌ها دوباره خرید می‌کنند؟",
        "خرید مجدد در کسب‌وکار من چقدر رایج است؟",
        "سهم مشتری تکراری از درآمد چقدر است؟",
        "وفاداری مشتریان من چطور است؟",
        "مشتری‌هایی که بیش از یک بار خرید کردند چند نفرند؟",
        "retention مشتری من چقدر است؟",
        "چقدر روی مشتری‌های قدیمی حساب کنم؟",
        "چقدر از فروشم از آدم‌های همیشگی است؟",
        "مشتری‌ها یک بار می‌خرند و دیگر برنمی‌گردند؟",
        "کسی دوباره برمی‌گردد از من بخرد یا همه یک‌بار مصرفند؟",
    ),
    "customers": (
        "چند مشتری دارم؟",
        "چند مشتری جدید در این بازه آمد؟",
        "تمرکز فروش من روی چند مشتری است؟",
        "مشتری‌های خفته من چند نفرند؟",
        "پایگاه مشتریان من چقدر بزرگ است؟",
        "سهم پنج مشتری بزرگ از فروشم چقدر است؟",
        "چند نفر از من خرید کرده‌اند؟",
        "مشتری‌هایی که دیگر برنگشتند چقدرند؟",
        "تعداد خریداران من چقدر است؟",
        "مشتری غیرفعال چند تا دارم؟",
        "چقدر به چند مشتری بزرگ وابسته‌ام؟",
        "ترکیب مشتریان جدید و قدیمی چطور است؟",
        "مشتری‌های خوابیده که دیگر خرید نمی‌کنند چند نفرند؟",
        "چند نفر برای اولین بار از من خرید کردند؟",
        "چند تا آدم متفاوت از من خرید کردند و چندتاشان تازه‌وارد بودند؟",
        "چند نفر ماه‌هاست که دیگر خبری از آن‌ها نیست؟",
        "کسانی که پارسال خرید کردند و امسال پیدایشان نشد چند نفرند؟",
    ),
    "psp": (
        "کدام درگاه بانکی بهتر است؟",
        "پی‌اس‌پی ضعیف من کدام است؟",
        "مسیردهی تراکنش‌ها را چطور بهتر کنم؟",
        "نرخ موفقیت هر درگاه چقدر است؟",
        "روی کدام گیت‌وی بیشتر خطا می‌خورم؟",
        "اختلاف بین درگاه‌های بانکی من معنادار است؟",
        "psp routing من چطور است؟",
        "کدام psp را کنار بگذارم؟",
        "درگاه پرداخت من مشکل دارد؟",
        "بین درگاه‌ها کدام بیشترین موفقیت را دارد؟",
        "شبکه بانکی کدام رِیل بهتر جواب می‌دهد؟",
        "تراکنش را به کدام درگاه بفرستم؟",
    ),
    "priorities": (
        "این هفته روی چه چیزی تمرکز کنم؟",
        "بزرگ‌ترین فرصت من چیست؟",
        "چه اقدامی بیشترین اثر را دارد؟",
        "چطور فروشم را بالا ببرم؟",
        "چه پیشنهادی برای بهبود داری؟",
        "مهم‌ترین کاری که باید بکنم چیست؟",
        "از کجا شروع کنم که بیشترین سود را بگیرم؟",
        "توصیه‌ات برای رشد کسب‌وکارم چیست؟",
        "چیکار کنم درآمدم بیشتر شود؟",
        "اولویت‌های من کدامند؟",
        "فرصت‌های بهبود من چیست؟",
        "برنامه پیشنهادی برای این ماه چیست؟",
        "کدام اقدام بیشترین بازگشت را دارد؟",
        "راهکار افزایش فروش من چیست؟",
        "چه کاری باید انجام بدهم؟",
        "اگر فقط یک چیز را درست کنم، کدام بیشتر پول اضافه می‌کند؟",
        "چقدر پول از دست دادم و چطور برش گردانم؟",
        "کجا دارم پول از دست می‌دهم؟",
    ),
    "gmv": (
        "فروش موفق من چقدر بوده؟",
        "درآمد کل من در این بازه چقدر است؟",
        "نرخ تبدیل من چند درصد است؟",
        "چند پرداخت موفق داشتم؟",
        "میانگین مبلغ سبد خرید من چقدر است؟",
        "خلاصه عملکرد کسب‌وکارم را بگو",
        "کل مبلغ تراکنش‌های موفق چقدر شد؟",
        "وضعیت کلی کسب‌وکار من چطور است؟",
        "چقدر پول گرفتم؟",
        "متوسط ارزش هر خرید چقدر است؟",
        "شاخص‌های اصلی من چیست؟",
        "گزارش خلاصه بده",
        "تعداد جلسه‌های پرداخت من چقدر بود؟",
        "کارنامه فروش من را بگو",
        "مبلغ فروش این دوره چقدر شد؟",
        "چقدر فروختم؟",
        "این ماه چقدر فروش داشتم؟",
        "هر مشتری معمولاً چقدر پول می‌گذارد؟",
        "نرخ conversion من الان چند است؟",
        "revenue من در این دوره چقدر بود؟",
        "از هر صد نفری که تا پای پرداخت می‌آیند چند نفر پول می‌دهند؟",
        "از هر ده نفر آخرش چند نفر پرداخت را کامل می‌کنند؟",
    ),
    "paid_unverified": (
        "پرداخت تاییدنشده چقدر است؟",
        "چقدر پول تسویه شده ولی تایید نکردم؟",
        "تراکنش‌های Paid که Verify نشده‌اند چندتاست؟",
        "پول بلاتکلیف من چقدر است؟",
        "مبلغی که در بانک تسویه شده ولی تایید نشده چقدر است؟",
        "چند تراکنش منتظر تایید مانده؟",
        "پرداخت‌های تایید نشده را نشانم بده",
        "چقدر درآمد معلق دارم چون تایید نکردم؟",
        "verify نشده‌ها چقدرند؟",
        "پول تسویه‌شده بدون تایید چقدر است؟",
        "تاییدنشده‌های من چه وضعی دارند؟",
        "چقدر پول روی میز جا گذاشتم؟",
    ),
    "fee": (
        "کارمزد من چقدر است؟",
        "شاخص نسبی کارمزد من چه وضعی دارد؟",
        "چقدر هزینه کارمزد می‌دهم؟",
        "سهم کارمزد از درآمدم چقدر است؟",
        "کمیسیون پرداختی من چقدر شده؟",
        "کارمزد تراکنش‌هایم را نشان بده",
        "هزینه درگاه برای من چقدر تمام می‌شود؟",
        "کارمزدم نسبت به فروشم زیاد است؟",
        "رقمی که بابت هر تراکنش از من برمی‌دارند چقدر است؟",
    ),
    "amount_bands": (
        "کدام بازه مبلغی بیشتر شکست می‌خورد؟",
        "خریدهای گران‌تر کمتر موفق می‌شوند؟",
        "نرخ تبدیل در بازه‌های قیمتی مختلف چطور است؟",
        "سفارش‌های با مبلغ بزرگ مشکل دارند؟",
        "رابطه مبلغ تراکنش و موفقیت پرداخت چیست؟",
        "در چه دامنه مبلغی بهترین تبدیل را دارم؟",
        "تراکنش‌های کم‌مبلغ بهتر جواب می‌دهند؟",
        "تبدیل بر حسب اندازه مبلغ چطور تغییر می‌کند؟",
        "سقف مبلغ روی موفقیت پرداخت اثر دارد؟",
        "برای مبالغ بالا نرخ موفقیتم چند است؟",
    ),
}

# --- discriminative anchors -----------------------------------------------------------
# The vocabulary that actually separates one intent from another, as opposed to the
# vocabulary every payment question shares («چقدر», «فروش», «من»). Example questions alone
# are not enough: a leave-one-out sweep over the bank plateaued at 0.55-0.60 for every
# scoring scheme tried (centroid, nearest-example, BM25, naive Bayes — see the bake-off in
# the journal), because thirteen Persian intents about one business share most of their
# words. Anchors are pooled into each intent's document a fixed number of times, so they
# raise the weight of the terms that decide the class without a second scoring path.
#
# Overlaps are intentional and harmless: «درگاه» anchors both psp and friction, «مشتری»
# both customers and repeat. IDF is computed after pooling, so a term claimed by many
# intents automatically loses most of its weight — the anchors do not have to be disjoint,
# only *true*.
ANCHOR_REPEAT = 4

ANCHORS: dict[str, tuple[str, ...]] = {
    "changes": ("افت فروش", "کاهش درآمد", "تغییر فروش", "رشد فروش", "نسبت به دوره قبل",
                "ماه قبل", "دلیل افت", "علت کاهش", "روند", "تجزیه تغییر", "چرا کم شد", "یهو", "بالا رفت", "ریخت",
                "بخاطر", "تعداد مشتری یا مبلغ", "پرید بالا", "از کجا آمد",
                "قد نمی دهد", "چه چیزی تغییر کرده"),
    "hours": ("ساعت", "ساعتی", "زمان روز", "صبح", "شب", "ظهر", "پیک", "بازه ساعتی"),
    "recovery": ("تلاش مجدد", "تلاش دوباره", "بازیابی", "نجات", "ریکاوری", "retry",
                 "بار دوم", "دوباره پرداخت", "بعد از شکست"),
    "friction": ("شکست", "ناموفق", "خطای بانکی", "رها", "انصراف", "ریزش", "قیف پرداخت",
                 "اصطکاک", "نیمه کاره", "جا زدن", "صفحه بانک", "از دست دادن",
                 "fail", "می پرند", "کجا می پرن", "رها کردن"),
    "peers": ("مقایسه", "همتا", "رقیب", "مشابه", "هم رده", "هم اندازه", "هم صنف",
              "صدک", "رتبه", "بنچمارک", "بازار", "جایگاه", "میانگین صنعت"),
    "repeat": ("مشتری تکراری", "برگشتی", "وفادار", "وفاداری", "بازگشت مشتری",
               "خرید مجدد", "دوباره خرید", "retention",
               "همیشگی", "آدم های همیشگی", "یک بار مصرف", "دوباره برمی گردد",
               "دیگر برنمی گردند", "بارها خرید"),
    "customers": ("تعداد مشتری", "مشتری جدید", "خریدار", "خفته", "غیرفعال",
                  "تمرکز مشتری", "وابسته به مشتری", "پایگاه مشتری", "چند مشتری",
                  "خوابیده", "دیگر خرید نمی کنند", "برنگشتند", "اولین بار خرید",
                  "چند تا آدم", "آدم متفاوت", "تازه وارد", "خبری نیست",
                  "پیدایشان نشد", "ماه هاست"),
    "psp": ("درگاه", "پی اس پی", "psp", "گیت وی", "gateway", "ریل بانکی",
            "مسیردهی", "routing", "درگاه بانکی", "شبکه بانکی"),
    "priorities": ("تمرکز", "اولویت", "فرصت", "پیشنهاد", "توصیه", "اقدام", "راهکار",
                   "بهبود", "چیکار کنم", "از کجا شروع", "برنامه", "بالا ببرم", "بیشترین اثر",
                   "از دست دادم", "از دست می دهم", "پول از دست"),
    "gmv": ("فروش موفق", "درآمد کل", "gmv", "نرخ تبدیل", "مبلغ کل", "خلاصه",
            "عملکرد کلی", "شاخص اصلی", "کارنامه", "چقدر فروختم", "سبد خرید",
            "conversion", "revenue", "چقدر فروش داشتم",
            # NOT the bare «چقدر پول»: it also opens «چقدر پول از دست دادم؟», and at anchor
            # weight x4 that pulled a loss question into the revenue answer — the merchant
            # asked what they lost and was told, at high confidence, what they earned.
            "چقدر پول گرفتم", "چقدر پول رسید",
            "از هر صد نفر", "از هر ده نفر", "چند نفر پول می دهند", "عدد کلی",
            "میانگین خرید", "تعداد پرداخت موفق"),
    "paid_unverified": ("تاییدنشده", "تایید نشده", "وریفای", "verify", "تسویه شده",
                        "بلاتکلیف", "معلق", "منتظر تایید", "paid", "بدون تایید"),
    "fee": ("کارمزد", "کمیسیون", "هزینه تراکنش", "fee", "هزینه درگاه",
            "بابت هر تراکنش برمی دارند", "رقمی که برمی دارند"),
    "amount_bands": ("بازه مبلغی", "بازه قیمتی", "گران", "ارزان", "دامنه مبلغ",
                     "سفارش بزرگ", "کم مبلغ", "سقف مبلغ", "اندازه مبلغ", "مبالغ بالا"),
}
assert set(ANCHORS) == set(BANK), "every intent needs anchors and vice versa"

# --- vector spaces ------------------------------------------------------------------
# Centroid (Rocchio) retrieval, not nearest-example. With a dozen examples per intent,
# nearest-example is dominated by whichever single example happens to share a word:
# removing one example removes the only occurrence of its distinctive term, and the
# leave-one-out score drops by ~13 points. The centroid pools an intent's whole
# vocabulary, so no single example carries the class.
#
# IDF is computed over the INTENT documents, not the individual examples: a term that
# appears under 12 of 13 intents («چقدر», «من», «است») then earns almost no weight, which
# is exactly the discrimination this router needs and what per-example IDF failed to give.


def _tfidf(term_lists: list[list[str]]) -> tuple[dict[str, float], list[dict[str, float]]]:
    n = len(term_lists)
    df: dict[str, int] = defaultdict(int)
    for terms in term_lists:
        for term in set(terms):
            df[term] += 1
    idf = {term: math.log((n + 1) / (d + 1)) + 1.0 for term, d in df.items()}
    return idf, [_vec(terms, idf) for terms in term_lists]


def _vec(terms: list[str], idf: dict[str, float]) -> dict[str, float]:
    tf: dict[str, float] = defaultdict(float)
    for term in terms:
        tf[term] += 1.0
    # sublinear tf: a word repeated three times is not three times the evidence — and in a
    # centroid, a word used by three of an intent's examples must not swamp the rest.
    v = {term: (1.0 + math.log(c)) * idf[term] for term, c in tf.items() if term in idf}
    norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
    return {term: x / norm for term, x in v.items()}


def _cos(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(x * b[term] for term, x in a.items() if term in b)


@dataclass(frozen=True)
class _Index:
    """One intent-centroid TF-IDF space: shared idf + the centroid of every intent."""
    idf: dict[str, float]
    centroids: tuple[tuple[str, dict[str, float]], ...]

    def score(self, terms: list[str]) -> dict[str, float]:
        qv = _vec(terms, self.idf)
        return {intent: _cos(qv, cv) for intent, cv in self.centroids}


def _intent_doc(intent: str, examples: tuple[str, ...], featurise) -> list[str]:
    """An intent's pooled feature document: every example, plus its anchors repeated
    ANCHOR_REPEAT times. Sublinear tf keeps the repetition bounded (×4 counts as ×2.4),
    so anchors weight the class without erasing what the examples contribute."""
    terms = [t for ex in examples for t in featurise(ex)]
    anchors = [t for a in ANCHORS.get(intent, ()) for t in featurise(a)]
    return terms + anchors * ANCHOR_REPEAT


def build_index(bank: dict[str, tuple[str, ...]]) -> tuple[_Index, _Index]:
    """(word index, char-gram index) over `bank`. Exposed so the calibrator can rebuild
    a held-out bank without reaching into module state."""
    intents = list(bank)
    w_idf, w_cent = _tfidf([_intent_doc(i, bank[i], tokens) for i in intents])
    c_idf, c_cent = _tfidf([_intent_doc(i, bank[i], char_grams) for i in intents])
    return (_Index(w_idf, tuple(zip(intents, w_cent))),
            _Index(c_idf, tuple(zip(intents, c_cent))))


_WORD_INDEX, _CHAR_INDEX = build_index(BANK)

# Blend: the word space carries topic, the character space carries morphology and survives
# the missing ZWNJ, the Arabic ك/ي and the typos that break word matching. The weight and
# both thresholds are set by leave-one-out cross-validation over the bank alone
# (pipeline/calibrate_nlu.py) — never against the held-out evaluation set.
_W_WEIGHT = 0.55
_C_WEIGHT = 0.45

# ACCEPT: route to the retrieved intent.
# Between REJECT and ACCEPT: on topic, but the router cannot tell WHICH question — ask,
#   and offer the nearest answerable questions, instead of answering a different one.
# Below REJECT: nothing in the product is close enough. Decline.
#
# Set from the LOO sweep, where 153/166 held-out bank questions route correctly (92.2%):
# their scores run min 0.103 / p05 0.130 / p50 0.253, while nine deliberately unrelated
# probes (weather, restaurants, capitals, a prompt-injection attempt, gibberish) top out
# at 0.109. The two distributions nearly touch, so the thresholds are placed to favour
# answering: 0.13 keeps 148 of the 153 correct routes, and the misroutes it lets through
# are all adjacent-intent (repeat↔customers, changes↔gmv) — a neighbouring answer about
# the same subject, not a different subject. Pushing ACCEPT to 0.22 to block those three
# would cost 46 correct answers, which is a much worse trade for a merchant.
ACCEPT = 0.13
REJECT = 0.10


@dataclass
class Match:
    intent: str
    score: float
    margin: float                     # gap to the next intent — a low margin is real ambiguity
    ranked: list[tuple[str, float]] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

    @property
    def decision(self) -> str:
        if self.score >= ACCEPT:
            return "route"
        if self.score >= REJECT:
            return "clarify"
        return "decline"


def score_intents(question: str, index: tuple[_Index, _Index] | None = None) -> list[tuple[str, float]]:
    """(intent, similarity) for every intent, best first. Deterministic: ties break on the
    intent id, so the same question never routes two different ways."""
    w_index, c_index = index or (_WORD_INDEX, _CHAR_INDEX)
    ws = w_index.score(tokens(question))
    cs = c_index.score(char_grams(question))
    merged = {i: _W_WEIGHT * ws.get(i, 0.0) + _C_WEIGHT * cs.get(i, 0.0) for i in ws}
    return sorted(merged.items(), key=lambda kv: (-kv[1], kv[0]))


def _nearest_examples(question: str, ranked: list[tuple[str, float]], k: int = 3) -> list[str]:
    """One representative question from each of the k best-matching intents — what the
    product offers back when it cannot route: things it CAN answer that look like the ask."""
    return [BANK[intent][0] for intent, _s in ranked[:k] if intent in BANK]


def route(question: str) -> Match:
    ranked = score_intents(question)
    top_intent, top_score = ranked[0]
    runner_up = ranked[1][1] if len(ranked) > 1 else 0.0
    return Match(intent=top_intent, score=round(top_score, 4),
                 margin=round(top_score - runner_up, 4),
                 ranked=[(i, round(s, 4)) for i, s in ranked[:5]],
                 suggestions=_nearest_examples(question, ranked))
