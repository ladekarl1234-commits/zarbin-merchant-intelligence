# معماری | Architecture

## جریان داده

```
other_challenge_data.csv.gz  (۶۱MB gz، ۲.۲M ردیف تلاش)
        │  zarin/pipeline.py — یک بار، ~۳۰-۷۰ ثانیه
        │  • assert های صحت قبل و بعد از ساخت (grain، سازگاری درون‌جلسه‌ای، عدم گم‌شدن ردیف)
        ▼
data/marts/*.parquet
  sessions         یک ردیف بر جلسه: outcome پنج‌حالته، first/last try، recovered، کارت برنده، ...
  attempts         تلاش‌های واقعی (try_seq>0) برای تحلیل PSP/کد خطا و drill-down
  merchant_daily   تجمیع پذیرنده×روز — پایه KPI و نرخ‌های همتایان هم‌دوره
  customers        پذیرنده×کارت: اولین/آخرین خرید، تعداد، GMV — پایه تکرار/کوهورت
  merchant_stats   پروفایل کل‌دوره هر پذیرنده — پایه انتخاب همتا و پیش‌فرض‌های دمو
        │  zarin/db.py — DuckDB in-process، viewهای read_parquet، thread-safe (RLock)
        ▼
zarin/api.py (FastAPI, پورت 8630)
  /api/meta /overview /insights /funnel /customers /peers /changes /copilot
  /api/evidence/sessions (drill-down تا session_key) /api/quality
  + سرو استاتیک frontend (SPA؛ zarin/static کامیت‌شده)
        ▼
frontend/ — Vite + React 18 + TypeScript strict، RTL کامل، Vazirmatn باندل‌شده،
  recharts فقط برای روند روزانه؛ قیف/صدک/آبشار/کوهورت SVG-CSS دست‌ساز.
```

## لایه معنایی (هسته ردیابی)

`zarin/registry.py` تنها جای تعریف متریک‌هاست (نام فارسی، تعریف، فرمول، دانه، هشدارها).
هر تابع تحلیلی خروجی + `evidence(...)` برمی‌گرداند که شامل **همان SQL اجراشده** و پارامترهاست؛
کشوی شواهد UI فقط این payload را رندر می‌کند. مسیر کامل:
**بینش ← متریک ← فرمول ← SQL ← نمونه session_key در دیتاست خام.**

## کارایی

- تجمیع‌های پذیرنده روی merchant_daily (~۶۰k ردیف) در حد میلی‌ثانیه؛ سنگین‌ترین کوئری‌ها
  (کوهورت، پنجک مبلغ) روی sessions با فیلتر پذیرنده — زیر ~۳۰۰ms.
- مرورگر هیچ تجمیعی انجام نمی‌دهد؛ فقط JSON کوچک رندر می‌شود.
- `/api/meta` با `lru_cache` کش می‌شود (ثابت در طول عمر پروسه).
- بسته JS ‏~۵۷۰KB (عمدتاً recharts) — برای اجرای لوکال هکاتون قابل قبول؛ در صورت نیاز
  code-splitting مسیر بهبود است.

## اجراپذیری

- `uv run zarin`: در نبود marts، pipeline را اجرا و سپس uvicorn را بالا می‌آورد.
- بدون کلید API، بدون شبکه، بدون دیتابیس خارجی؛ فقط دیتاست + پایتون.
- `ZARIN_DATA_PATH` و `ZARIN_MARTS_DIR` و `ZARIN_PORT` قابل‌تنظیم‌اند.
- Dockerfile/compose برای محیط‌های کانتینری (مسیر مرجع تست‌شده: uv).

## تست‌پذیری

- `tests/conftest.py` دیتاست مصنوعی ۱۲ردیفه با تمام حالت‌های خطرناک می‌سازد و همان
  pipeline واقعی را روی آن اجرا می‌کند (env-var override؛ بدون mock).
- `pipeline/validate.py` مسیر مستقل: CSV خام → SQL مستقل → مقایسه با API زنده.
