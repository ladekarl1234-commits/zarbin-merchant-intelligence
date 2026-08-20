# زرین‌بین · Zarbin

### Merchant Intelligence + AI Operations for ZarinPal

زرین‌بین فقط یک داشبورد BI نیست. محصول دو فضای هماهنگ دارد که یک موتور داده و متریک مشترک را استفاده می‌کنند:

**داشبورد پذیرنده** برای اینکه صاحب کسب‌وکار خیلی ساده بفهمد «چه اتفاقی افتاده، چرا، چقدر مهم است، چه کاری انجام بدهم و این عدد از کجا آمده؟»

**مرکز کنترل** برای تیم Business / Product / Data / Engineering تا علاوه بر وضعیت کل داده، performance، turnaround/latency، هزینه، سلامت منابع داده و کیفیت خودِ AI را ببیند.

> **Data → deterministic metrics → actionable insight → evidence → optional AI explanation**
>
> مدل زبانی منبع حقیقت اعداد نیست.

---

## ▶ اجرا و مشاهده

پیش‌نیاز اصلی: [uv](https://docs.astral.sh/uv/). برای مسیر اصلی Node لازم نیست؛ build فرانت داخل پروژه سرو می‌شود.

```bash
git clone https://github.com/ladekarl1234-commits/zarbin-merchant-intelligence.git
cd zarbin-merchant-intelligence
git switch feature/dual-surface-ai-ops

# دیتاست چالش:
# data/other_challenge_data.csv.gz
# یا: ZARIN_DATA_PATH=/path/to/file.csv.gz

uv run zarin
```

### 🔗 http://localhost:8630

در VS Code نیز می‌توانید از **Terminal → Run Task → Run Zarbin Dashboard** استفاده کنید.

برای تست و build:

```bash
uv run pytest -q
uv run ruff check .
npm --prefix frontend ci
npm --prefix frontend run build
```

---

## دو فضای محصول

### 1) داشبورد پذیرنده

برای پذیرنده‌ای که تحلیل‌گر داده نیست:

- **نمای کلی و Action Feed** — مهم‌ترین فرصت‌ها و هشدارها، نه دیوار نمودار؛
- **قیف پرداخت** — NoAttempt، رهاشدن در بانک، شکست صریح، Paid-but-unverified و Verified جدا از هم؛
- **Payment Rescue** — پرداخت‌هایی که بعد از retry واقعاً نجات یافته‌اند؛
- **مشتریان** — جدید/تکراری، cohort، تمرکز و مشتری ارزشمند غیرفعال؛
- **همتایان رفتاری** — مقایسه با کسب‌وکار هم‌صنف و هم‌مقیاس با suppression نمونه کوچک؛
- **چه چیزی تغییر کرد؟** — تجزیه تغییر فروش به حجم، تبدیل و مبلغ خرید؛
- **Ask Your Business** — پرسش فارسی با متن یا **Voice-to-Text**؛
- **Evidence Drawer** — تعریف، فرمول، روش/SQL، sample size، caveat و drill-through به sessionهای منبع.

### 2) مرکز کنترل · Business / Technical / AI Ops

این بخش خودِ زرین‌بین را پایش می‌کند:

- تعداد پذیرنده و sessionهای تحت پوشش؛
- AI request volume؛
- **Grounded-answer rate**؛
- **Fallback rate**؛
- average و P95 latency / turnaround؛
- model mix و intent mix؛
- هزینه مدل ثبت‌شده؛
- recent AI requests؛
- سلامت منبع داده؛
- Google Analytics connection/snapshot؛
- insightهای مشتق‌شده از منبع جدید؛
- **Voice Mode مدیریتی** برای پرسیدن درباره سرعت، fallback، هزینه و source health.

اصطلاحات فنی که برای همه واضح نیستند با hover/focus tooltip توضیح داده می‌شوند تا UI شلوغ نشود.

---

## AI: مفید، ولی تحت کنترل

### OpenRouter

اتصال بیرونی اختیاری است و مدل پیش‌فرض:

```text
openrouter/free
```

است.

```bash
export OPENROUTER_API_KEY=...
export OPENROUTER_MODEL=openrouter/free
uv run zarin
```

معماری Copilot عمداً LLM-first نیست:

```text
Question
  ↓
Deterministic Analytics
  ↓
Evidence-safe Context
  ↓
Optional OpenRouter explanation
  ↓
Answer + provenance + telemetry
```

اگر OpenRouter خطا بدهد یا کلید وجود نداشته باشد، پاسخ deterministic داخلی کار می‌کند. قبل از ارسال context به provider بیرونی، raw session/card data، SQL parameters و ردیف‌های حساس حذف می‌شوند.

### AI خودش هم اندازه‌گیری می‌شود

مرکز کنترل حداقل این موارد را ثبت می‌کند:

- latency؛
- groundedness؛
- fallback؛
- success؛
- model؛
- intent؛
- cost؛
- error/fallback state.

این یعنی سؤال فقط «AI داریم؟» نیست؛ سؤال «AI واقعاً خوب کار می‌کند؟» هم بخشی از محصول است.

---

## Google Analytics 4 و داده‌های آینده

هسته به CSV چالش قفل نشده است. `zarin/connectors.py` مرز اتصال منابع بیرونی است.

برای GA4:

```bash
uv sync --group connectors
export GA4_PROPERTY_ID=123456789
export GOOGLE_APPLICATION_CREDENTIALS=/secure/path/service-account.json
```

سپس endpoint همگام‌سازی می‌تواند snapshot bounded بسازد. منبع جدید **فقط نمایش داده نمی‌شود**: بعد از sync، قواعد deterministic تغییرات معنادار را به insight تبدیل می‌کنند؛ در مرحله بعد AI فقط همان insight و evidence را توضیح می‌دهد.

GA4 سیگنال مکمل traffic/acquisition/behavior است و جایگزین payment truth نیست. قبل از join کردن داده‌های چند منبع، identity، timezone و attribution semantics باید صریح تعریف و تست شوند.

---

## چرا این Stack؟

| لایه | انتخاب فعلی | دلیل |
|---|---|---|
| Frontend | React + Vite + TypeScript | SPA تحلیلی سریع، کم‌پیچیدگی، judge-friendly |
| API | FastAPI | نزدیکی به data-science stack، OpenAPI و مرز روشن domain API |
| Analytics | DuckDB + Parquet | برای چند میلیون ردیف OLAP بسیار سریع و ساده، بدون warehouse سنگین |
| Metrics | semantic/registry + deterministic Python/SQL | یک منبع حقیقت و traceability |
| AI | provider adapter + OpenRouter free route | قابل تعویض، fallback-safe، cost-aware |
| External data | connector adapters | GA4 و منابع بعدی بدون شکستن metric core |

**نکته مهم:** این stack بهترین fit برای challenge و single-node production-shaped deployment است، نه ادعای «بی‌نهایت horizontally scalable». مسیر scale صریحاً در ADR نوشته شده است.

برای جزئیات و trade-offها: [`docs/ADR/0001-platform-stack-and-scale.md`](docs/ADR/0001-platform-stack-and-scale.md)

---

## معماری

```text
                     ┌──────────────────────────────┐
                     │          Sources             │
                     │ ZarinPal CSV · GA4 · future  │
                     └──────────────┬───────────────┘
                                    │ adapters
                                    ▼
                     ┌──────────────────────────────┐
                     │ Validation / Semantic Layer  │
                     │ session grain · metric defs  │
                     └──────────────┬───────────────┘
                                    ▼
             ┌──────────────────────────────────────────┐
             │ DuckDB / Parquet + Deterministic Engine │
             │ analytics · peers · changes · insights  │
             └─────────────┬────────────────┬───────────┘
                           │                │
                  evidence│                │safe context
                           ▼                ▼
                  ┌──────────────┐   ┌─────────────────┐
                  │ Merchant API │   │ AI Gateway      │
                  │ + lineage    │   │ OpenRouter/free │
                  └──────┬───────┘   │ + fallback     │
                         │           └────────┬────────┘
                         │                    │ telemetry
              ┌──────────▼──────────┐  ┌──────▼──────────────┐
              │ Merchant Dashboard │  │ Control Center      │
              │ insights + voice   │  │ Business + AI Ops  │
              └─────────────────────┘  └─────────────────────┘
```

### مسیر scale واقعی

وقتی multi-tenant/concurrency نیاز ایجاد کند، بدون تغییر semantic metrics:

- raw/Parquet → Object Storage؛
- control-plane state → Postgres؛
- OLAP concurrency → ClickHouse / warehouse؛
- ingestion → Queue + Workers؛
- telemetry → OpenTelemetry + durable observability backend؛
- identity → OIDC/RBAC + tenant isolation؛
- secrets → Secret Manager.

جزئیات: [`docs/DEPLOYMENT_SPEC.md`](docs/DEPLOYMENT_SPEC.md)

---

## نوآوری‌های مهم

- **Paid-but-unverified**: پول settle شده اما پذیرنده verification نهایی را کامل نکرده؛ outcome مستقل، نه «failure» عمومی.
- **Payment Rescue**: سنجش retry recovery بدون double-count کردن session/GMV.
- **Opportunity Engine**: gap/counterfactual با scenario band و guardrail، نه جمع مبالغ شکست‌خورده.
- **Matched Peers**: benchmark قابل توضیح و suppression برای peer pool کوچک.
- **What Changed**: decomposition دقیق فروش به drivers، نه صرفاً «فروش ۱۲٪ کم شد».
- **Evidence as Product**: کاربر از insight تا formula/query/source session پایین می‌رود.
- **AI observing AI**: کیفیت خودِ لایه هوشمند بخشی از داشبورد مدیریت است.
- **Evidence-safe external AI**: provider بیرونی حق دسترسی مستقیم به raw data ندارد.
- **Data-source-to-insight**: connector جدید فقط chart تولید نمی‌کند؛ ابتدا deterministic insight می‌سازد.

---

## Design System

اصل طراحی:

> **ساده‌ترین رابطی که تصمیم را منتقل می‌کند.**

- Persian-first و RTL؛
- Vazirmatn؛
- زرد برند فقط برای action/stateهای مهم؛
- progressive disclosure؛
- chart فقط وقتی تصمیمی را روشن می‌کند؛
- Evidence Drawer برای جزئیات فنی؛
- hover/focus tooltip برای اصطلاح دشوار؛
- mobile hierarchy واقعی؛
- Voice به‌عنوان shortcut، نه وابستگی اجباری.

جزئیات: [`docs/DESIGN.md`](docs/DESIGN.md) و [`docs/PLATFORM_BOOK.md`](docs/PLATFORM_BOOK.md)

---

## برای توسعه‌دهنده بعدی

مسیرها عمداً واضح هستند:

```text
Metric meaning       → zarin/registry.py
Deterministic logic  → zarin/analytics.py
Merchant actions     → zarin/insights.py
Peer methodology     → zarin/peers.py
AI policy/telemetry  → zarin/ai_ops.py
External sources     → zarin/connectors.py
HTTP surface         → zarin/api.py
Merchant UI          → frontend/src/pages/*
Control Center       → frontend/src/pages/AdminPage.tsx
Voice                → frontend/src/components/VoiceInput.tsx
```

بخوانید: [`CONTRIBUTING.md`](CONTRIBUTING.md) و [`memory.md`](memory.md).

---

## مستندات کلیدی

| سند | هدف |
|---|---|
| [`docs/DATA_AUDIT.md`](docs/DATA_AUDIT.md) | grain، وضعیت‌ها، nullها، confounderها و محدودیت‌های واقعی داده |
| [`docs/ANALYTICS.md`](docs/ANALYTICS.md) | methodology و metric logic |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | معماری challenge engine |
| [`docs/ADR/0001-platform-stack-and-scale.md`](docs/ADR/0001-platform-stack-and-scale.md) | چرا این stack و مسیر scale |
| [`docs/DEPLOYMENT_SPEC.md`](docs/DEPLOYMENT_SPEC.md) | runtime profiles، env contract، SLO و production target |
| [`docs/PLATFORM_BOOK.md`](docs/PLATFORM_BOOK.md) | داستان کامل محصول، innovation، AI/data contract و design philosophy |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | تصمیم‌های تحلیلی/محصولی قبلی |
| [`docs/VALIDATION.md`](docs/VALIDATION.md) | validation مستقل اعداد |
| [`docs/JURY_REVIEW.md`](docs/JURY_REVIEW.md) | adversarial jury و deductions |
| [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md) | سناریوی دمو |
| [`memory.md`](memory.md) | حافظه پایدار برای ادامه کار انسان/Agent |

---

## امنیت و حریم داده

- raw challenge data و `data/` gitignored هستند؛
- OpenRouter key و Google credentials فقط از environment خوانده می‌شوند؛
- context مدل بیرونی aggregate/evidence-safe است؛
- اپ در local mode روی localhost bind می‌شود؛
- قبل از internet exposure باید auth/RBAC، tenant isolation، secret manager، rate limiting و audit policy اضافه شود.

---

## وضعیت deployment

### Local / judge

```bash
uv run zarin
# http://localhost:8630
```

### Connected demo

OpenRouter و GA4 اختیاری‌اند؛ نبود آن‌ها Merchant Analytics را از کار نمی‌اندازد.

### Production

Spec و migration path موجود است، اما evaluator build را با SaaS multi-tenant production اشتباه نمی‌گیریم. این صداقت معماری عمدی است.

---

## Hackathon philosophy

Rubric به‌صورت مستقیم روی طراحی محصول اثر گذاشته است:

- **Actionability:** هر insight باید observation → diagnosis → impact → action داشته باشد.
- **Correctness:** metric registry + evidence + source drill-through.
- **Analytical depth:** segmentation، matched peers، decomposition، confounder control و restrained counterfactuals.
- **Nontechnical UX:** زبان ساده و progressive disclosure.
- **Technical quality:** deterministic core، tests، CI، deployment docs، ADR، extensibility و failure-safe AI.

هدف زرین‌بین این نیست که «داده بیشتری نشان بدهد»؛ هدف این است که **تصمیم بهتر بسازد و بتواند ثابت کند چرا آن تصمیم را پیشنهاد داده است.**
