# Zarbin Project Memory

این فایل حافظهٔ کاری پایدار پروژه است تا هر توسعه‌دهنده یا Agent بتواند بدون بازخوانی کامل تاریخچه بفهمد محصول چرا این شکل را دارد و چه تصمیم‌هایی گرفته شده است.

## هویت محصول

زرین‌بین دو سطح هماهنگ دارد:

- **Merchant Intelligence**: برای خود پذیرنده؛ پاسخ ساده به «چه اتفاقی افتاده؟ چرا؟ چه کاری انجام بدهم؟ این عدد از کجا آمده؟»
- **Control Center / AI Ops**: برای مدیر کسب‌وکار، محصول و تیم فنی؛ سلامت داده، performance، latency/turnaround، هزینه، کیفیت پاسخ AI، fallback، مدل، منابع داده و قابلیت توسعه را پایش می‌کند.

## قواعد غیرقابل مذاکره

- منبع حقیقت اعداد، موتور deterministic analytics است؛ LLM اجازه ساخت عدد ندارد.
- هر ادعای مهم باید evidence و مسیر ردیابی داشته باشد.
- attempt با session یکی نیست؛ retry نباید GMV یا transaction count را چندبار بشمارد.
- `NoAttempt` از شکست بانکی جداست.
- `Paid` با `Verified` یکی نیست.
- `adjusted_fee` کارمزد واقعی زرین‌پال نیست و فقط شاخص نسبی است.
- شناسه کارت merchant-scoped است؛ cross-merchant customer tracking ممنوع.
- زبان Merchant UI باید ساده باشد؛ اصطلاح سخت یا حذف می‌شود یا با tooltip توضیح داده می‌شود.
- نمونه کم باید به suppression/احتیاط منجر شود، نه precision جعلی.

## معماری فعلی

- FastAPI: API و control plane
- DuckDB + Parquet: semantic marts و query تحلیلی
- React + Vite + TypeScript: Persian-first RTL frontend
- `zarin/registry.py`: تعریف مرکزی متریک‌ها
- `zarin/analytics.py`: analytics deterministic
- `zarin/insights.py`: action/opportunity engine
- `zarin/ai_ops.py`: optional OpenRouter explanation layer + telemetry
- `zarin/connectors.py`: adapter منابع بیرونی (فعلاً GA4)

## AI

- پیش‌فرض external model: `openrouter/free`.
- کلید فقط از `OPENROUTER_API_KEY` خوانده می‌شود؛ هرگز commit نشود.
- بدون کلید یا در خطا، deterministic copilot پاسخ می‌دهد.
- قبل از ارسال context به مدل بیرونی، session rows، SQL params و داده خام حذف می‌شوند.
- AI telemetry در `data/runtime/ai_events.jsonl` ذخیره می‌شود و gitignored باید بماند.
- معیارهای Ops: latency، grounded rate، fallback rate، success، model mix، intent mix و cost.

## External Data

Google Analytics 4 از طریق Adapter اختیاری اضافه شده است:

- `GA4_PROPERTY_ID`
- `GOOGLE_APPLICATION_CREDENTIALS`
- dependencies: `uv sync --group connectors`
- snapshot: `data/external/ga4_latest.json`

GA4 جایگزین داده پرداخت نیست؛ سیگنال مکمل برای traffic/acquisition/behavior است. join تحلیلی فقط وقتی تعریف مشترک و mapping معتبر وجود داشته باشد انجام می‌شود.

## UX

- دو Workspace واضح: «داشبورد پذیرنده» و «مرکز کنترل».
- Merchant UI insight-first و غیرتکنیکال است.
- Voice-to-text در مرورگر با `fa-IR` و graceful fallback.
- اصطلاحات سخت با hover/focus tooltip توضیح داده می‌شوند.
- Evidence Drawer امضای اصلی محصول است.

## محدودیت‌های فعلی

- DuckDB + فایل محلی برای چالش و single-node عالی است، اما horizontal multi-instance production storage نیست.
- telemetry AI فعلاً JSONL محلی است؛ برای production باید به Postgres/ClickHouse/OpenTelemetry sink منتقل شود.
- Voice recognition فعلاً browser-native است؛ Adapter برای STT داخلی سازمان باید در مرحله deployment سازمانی جایگزین/اضافه شود.
- GA4 فقط وقتی credential واقعی تنظیم شود sync می‌شود.
- authentication/RBAC هنوز evaluator-mode است.

## مسیر Scale

قبل از production multi-tenant:

1. auth/RBAC و tenant isolation؛
2. ingestion jobs + queue؛
3. object storage برای raw/Parquet؛
4. Postgres برای control-plane state؛
5. ClickHouse یا analytical warehouse برای concurrency بالا؛
6. OpenTelemetry برای traces/metrics؛
7. background worker برای GA4 و insight refresh؛
8. secret manager؛
9. model policy/allowlist و quality evaluation set؛
10. audit log immutable.

## تاریخچهٔ مهم

- دیتاست audit شد و grain به‌درستی attempt/session تفکیک شد.
- Paid-but-unverified به‌عنوان insight متمایز کشف شد.
- Retry recovery، matched peers و LMDI اضافه شد.
- Jury hardening دو دور انجام شد.
- repeat-rate sub-period bug اصلاح شد.
- opportunity engine از failed-sum فاصله گرفت و scenario band صادقانه شد.
- path traversal/UNC و API input handling سخت‌گیری شد.
- dual-surface architecture، OpenRouter free adapter، GA4 adapter، AI Ops و voice-to-text در branch `feature/dual-surface-ai-ops` اضافه شدند.

این فایل باید با هر تصمیم معماری/محصولی مهم به‌روزرسانی شود؛ نه با جزئیات ریز هر commit.
