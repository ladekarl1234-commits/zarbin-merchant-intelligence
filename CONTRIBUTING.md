# Contributing to Zarbin

هدف این راهنما این است که توسعه‌دهندهٔ جدید در کمتر از ۱۵ دقیقه بفهمد feature را کجا اضافه کند و چه قواعدی را نباید بشکند.

## شروع

```bash
uv run zarin
# http://localhost:8630

uv run pytest -q
uv run ruff check .
npm --prefix frontend run build
```

برای GA4:

```bash
uv sync --group connectors
```

## نقشهٔ کد

| نیاز | محل اصلی |
|---|---|
| تعریف/معنای متریک | `zarin/registry.py` |
| query و تحلیل deterministic | `zarin/analytics.py` |
| insight/action/opportunity | `zarin/insights.py` |
| peer methodology | `zarin/peers.py` |
| AI provider/policy/telemetry | `zarin/ai_ops.py` |
| منبع داده جدید | `zarin/connectors.py` |
| REST API | `zarin/api.py` |
| Merchant UI | `frontend/src/pages/*` |
| Control Center | `frontend/src/pages/AdminPage.tsx` |
| evidence UX | `frontend/src/components/EvidenceDrawer.tsx` |
| voice input | `frontend/src/components/VoiceInput.tsx` |
| design tokens/base | `frontend/src/theme.css` |
| control/voice styles | `frontend/src/ops.css` |

## قانون feature جدید

قبل از اضافه کردن یک insight بپرس:

1. عدد از کدام metric authoritative می‌آید؟
2. grain درست چیست؟
3. sample کافی است؟
4. آیا confounder مهمی داریم؟
5. آیا Merchant می‌فهمد چرا مهم است؟
6. اقدام واقعی چیست؟
7. Evidence Drawer چه چیزی نشان می‌دهد؟
8. آیا LLM می‌تواند بدون evidence این عدد را بسازد؟ اگر بله، طراحی غلط است.

## افزودن Data Source

هر connector جدید باید:

- credential را فقط از environment/secret manager بگیرد؛
- bounded fetch داشته باشد؛
- schema/freshness را validate کند؛
- raw payload را مستقیم به UI/LLM نفرستد؛
- mapping به semantic layer را مستند کند؛
- وضعیت connection/failure را در Control Center نشان دهد.

## افزودن AI provider

Provider جدید باید پشت AI Gateway بماند. خروجی analytics اول ساخته می‌شود و فقط context امن برای explanation به مدل داده می‌شود. هیچ provider نباید مستقیم به DuckDB/raw card/session data دسترسی داشته باشد.

## زبان و UX

- Merchant UI: اصطلاح ساده؛ واژه فنی فقط اگر لازم است، همراه tooltip.
- Internal Control Center: اصطلاح فنی مجاز است، اما definition باید روی hover/focus در دسترس باشد.
- RTL، موبایل، keyboard و contrast را بعد از تغییر تست کنید.

## تست‌های اجباری برای metric logic

تست باید failure mode را discriminate کند، نه فقط happy path را. نمونه‌ها: attempts≠sessions، retry double-count، Paid≠Verified، NoAttempt≠bank failure، merchant-scoped customer، low-n suppression، opportunity≠failed sum.

## اسناد

اگر تصمیم معماری/محصولی مهم عوض شد:

- `memory.md`
- ADR مرتبط یا ADR جدید
- `docs/DEPLOYMENT_SPEC.md` در صورت اثر عملیاتی
- `docs/PLATFORM_BOOK.md` در صورت اثر روی داستان محصول

را به‌روزرسانی کنید.
