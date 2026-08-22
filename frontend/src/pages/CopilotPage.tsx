import type { CopilotAnswer, Overview } from "../api";
import { get } from "../api";
import { useApp, useData } from "../ctx";
import { deltaPct, faNum, pct, rial } from "../fmt";
import Copilot, { type GlanceItem } from "../components/Copilot";

const PROMPTS = [
  { q: "این هفته روی چه تمرکز کنم؟", why: "فرصت‌ها به ترتیب اثر مالی" },
  { q: "چرا فروشم کم شد؟", why: "تجزیه دقیق، نه حدس" },
  { q: "چرا پرداخت‌ها شکست می‌خورند؟", why: "ریشه واقعی شکست‌ها" },
  { q: "در مقایسه با کسب‌وکارهای مشابه کجا هستم؟", why: "فقط همتایان واقعی" },
  { q: "مشتری‌ها چه ساعتی خرید می‌کنند؟", why: "برای زمان‌بندی کمپین" },
  { q: "مشتریان تکراری چقدر سهم دارند؟", why: "ارزش وفاداری" },
];

function delta(cur: number | null, prev: number | null | undefined): { d?: string; dColor?: string } {
  if (prev == null) return {};
  const dp = deltaPct(cur, prev ?? null);
  if (dp == null) return {};
  return { d: `${dp >= 0 ? "▲" : "▼"} ${pct(Math.abs(dp))}`, dColor: dp >= 0 ? "var(--good)" : "var(--bad)" };
}

export default function CopilotPage() {
  const { merchant, period } = useApp();
  const ov = useData<Overview>("overview", { cf: period.cf, ct: period.ct });
  const k = ov.data?.kpis;
  const p = ov.data?.previous;

  const glance: GlanceItem[] | undefined = k && [
    { k: "فروش موفق", v: rial(k.gmv, false), tip: "gmv", ...delta(k.gmv, p?.gmv) },
    { k: "نرخ تکمیل پرداخت", v: pct(k.conv), tip: "conv", ...delta(k.conv, p?.conv) },
    { k: "مشتریان", v: faNum(k.customers), tip: "customers", d: "پرداخت‌کننده", dColor: "var(--ink-3)" },
    ...(k.paid_unverified > 0 ? [{ k: "در انتظار تایید شما", v: rial(k.paid_unverified_amount, false),
        tip: "verify" as const, d: `${faNum(k.paid_unverified)} پرداخت`, dColor: "var(--warn)" }] : []),
  ];

  return (
    <Copilot
      heroTitle="از کسب‌وکارت چه خبر؟"
      heroSub="هر پاسخ از داده واقعی پرداخت‌های شما محاسبه می‌شود — قابل ردیابی تا تک‌تک تراکنش‌ها."
      glance={glance}
      suggestions={PROMPTS}
      placeholder="مثلاً: چرا فروشم کم شد؟"
      ask={(q) => get<CopilotAnswer>("copilot", { m: merchant, q, f: period.f, t: period.t, surface: "merchant" })}
      polish={(q) => get<CopilotAnswer>("copilot/polish", { m: merchant, q, f: period.f, t: period.t, surface: "merchant" })}
      onFeedback={(a, useful) =>
        get("copilot/feedback", { m: merchant, intent: a.intent, useful: String(useful), surface: "merchant" }, "POST").catch(() => {})}
    />
  );
}
