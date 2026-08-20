import type { CopilotAnswer } from "../api";
import { get } from "../api";
import { useApp } from "../ctx";
import Copilot from "../components/Copilot";

const SUGGESTIONS = [
  "این هفته روی چه تمرکز کنم؟",
  "چرا فروشم کم شد؟",
  "مشتری‌ها چه ساعتی خرید می‌کنند؟",
  "چرا پرداخت‌ها شکست می‌خورند؟",
  "تلاش مجدد چقدر فروش برگرداند؟",
  "در مقایسه با همتایان کجا هستم؟",
  "مشتریان تکراری چقدر سهم دارند؟",
];

export default function CopilotPage() {
  const { merchant, period } = useApp();
  return (
    <Copilot
      title="از کسب‌وکارت بپرس"
      sub="پاسخ‌ها از موتور تحلیلی قطعی می‌آیند؛ اگر مدل زبانی فعال باشد فقط جمله را ساده‌تر می‌کند و هیچ عددی را تغییر نمی‌دهد."
      suggestions={SUGGESTIONS}
      placeholder="مثلاً: چرا فروشم کم شد؟"
      emptyHint={`پاسخ همیشه بر اساس بازه انتخابی شما (${period.label}) محاسبه می‌شود.`}
      ask={(q) => get<CopilotAnswer>("copilot", { m: merchant, q, f: period.f, t: period.t, surface: "merchant" })}
      onFeedback={(a, useful) =>
        get("copilot/feedback", { m: merchant, intent: a.intent, useful: String(useful), surface: "merchant" }, "POST")
          .catch(() => {})}
    />
  );
}
