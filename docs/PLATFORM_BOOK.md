# Zarbin Platform Book

این سند تصویر کامل محصول را برای داور، مدیر محصول، مهندس و تحلیل‌گر توضیح می‌دهد.

## محصول در یک جمله

زرین‌بین دادهٔ پرداخت و منابع مکمل را به **تصمیم قابل اقدام و قابل ردیابی** تبدیل می‌کند و هم‌زمان کیفیت خودِ موتور تحلیل و AI را نیز اندازه می‌گیرد.

## دو فلوی محصول

### Merchant Intelligence

برای پذیرنده‌ای که می‌خواهد ساده و سریع بفهمد:

- چه اتفاقی افتاده؟
- چرا؟
- چه مقدار اهمیت مالی دارد؟
- چه کاری انجام بدهم؟
- نسبت به همتایان کجا هستم؟
- این عدد دقیقاً از کجا آمده؟

صفحه‌ها: Overview، Payment Funnel، What Changed، Peers، Customers، Ask/Voice، Data Quality.

### Control Center

برای مدیر کسب‌وکار، Product، Data و Engineering:

- platform performance؛
- AI turnaround/latency؛
- grounded-answer rate؛
- fallback rate؛
- model mix؛
- intent mix؛
- cost؛
- source health؛
- GA4 status/snapshot؛
- data-quality indicators؛
- Voice Mode برای گفت‌وگوی عملیاتی.

این جداسازی عمداً انجام شده تا Merchant UI به اصطلاحات فنی آلوده نشود، اما تیم داخلی همچنان جزئیات لازم برای کنترل کیفیت را داشته باشد.

## نوآوری‌های اصلی

- **Insight-first UX** به‌جای chart wall.
- **Evidence lineage** از insight تا metric/formula/query/session.
- **Paid-but-unverified** به‌عنوان outcome مستقل و عملیاتی.
- **Payment Rescue** برای سنجش ارزش retry واقعی.
- **Matched peers** با suppression در sample کوچک.
- **What Changed** با decomposition به‌جای توضیح کلی.
- **Opportunity Engine** با counterfactual gap و scenario band، نه جمع failed amount.
- **AI as explanation layer** نه calculator.
- **AI observing AI**: latency، groundedness، fallback و cost در Control Center.
- **Connector architecture** برای افزودن GA4 و منابع بعدی بدون تغییر metric core.

## Data & AI Contract

هر insight باید از این مسیر عبور کند:

`Source -> Validation -> Semantic Metric -> Deterministic Analysis -> Evidence -> Optional AI Explanation -> UI`

LLM حق ندارد Source را دور بزند.

### External AI

OpenRouter فقط وقتی `OPENROUTER_API_KEY` تنظیم شود فعال می‌شود. مدل پیش‌فرض `openrouter/free` است. Context بیرونی شامل داده خام کارت/جلسه یا SQL params نیست؛ مدل فقط answer/evidence خلاصه‌شده می‌بیند.

### Fallback

اگر مدل fail شود، پاسخ deterministic حذف نمی‌شود. Control Center fallback را ثبت می‌کند.

## Google Analytics

GA4 به‌عنوان **سیگنال مکمل acquisition/traffic/behavior** وارد می‌شود، نه جایگزین payment truth.

Adapter فعلی snapshot روزانه‌ای از sessions/users/events/purchaseRevenue می‌گیرد. قبل از ترکیب payment و GA4 باید identity/timezone/attribution semantics مشخص و تست شود.

## Design System

اصل طراحی: **ساده‌ترین رابطی که تصمیم را منتقل می‌کند**.

- Persian-first RTL؛
- Vazirmatn؛
- زرد برند برای action/state مهم، نه decoration دائمی؛
- progressive disclosure؛
- Evidence Drawer به‌عنوان جزئیات سطح دوم؛
- اصطلاح دشوار با hover/focus tooltip؛
- mobile hierarchy واقعی؛
- Voice input به‌عنوان shortcut، نه الزام.

## توسعه‌پذیری

Feature جدید بهتر است در یکی از این مرزها قرار بگیرد:

- Metric/semantic definition -> registry/analytics
- Merchant insight -> insights
- New data source -> connectors
- New AI provider/policy -> ai_ops
- Internal operational capability -> admin API + AdminPage
- UI-only explanation -> reusable component/tooltip

این تفکیک باعث می‌شود توسعه‌دهندهٔ جدید بداند feature را کجا اضافه کند و logic بین frontend/backend پخش نشود.

## Scalability

برای challenge و single-node، stack فعلی عمداً ساده است. برای SaaS واقعی، مسیر scale در ADR و Deployment Spec مشخص شده است. مهم‌ترین نکته این است که **metric semantics نباید هنگام مهاجرت زیرساخت تغییر کند**.

## کیفیت AI چگونه سنجیده می‌شود؟

حداقل telemetry فعلی:

- total requests؛
- latency avg/P95؛
- grounded rate؛
- fallback rate؛
- model mix؛
- intent mix؛
- cost؛
- recent request status.

مرحله production باید evaluation dataset، human feedback، hallucination/unsupported-claim detector و regression gates نیز اضافه کند.

## چرا این ساختار برای داوری قوی‌تر است؟

چون محصول دیگر فقط نشان نمی‌دهد «ما analytics ساخته‌ایم»؛ نشان می‌دهد:

- merchant value چیست؛
- methodology قابل دفاع است؛
- AI تحت کنترل است؛
- داده جدید قابل اتصال است؛
- تصمیم‌های معماری مستندند؛
- تیم بعدی می‌تواند توسعه دهد؛
- deployment و scale از قبل فکر شده است.
