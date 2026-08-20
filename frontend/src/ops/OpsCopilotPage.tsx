import type { CopilotAnswer } from "../api";
import { get } from "../api";
import { useApp } from "../ctx";
import Copilot from "../components/Copilot";

const PROMPTS = [
  { q: "وضعیت کل سیستم چطوره؟", why: "خلاصه سلامت پلتفرم" },
  { q: "AI امروز چطور عمل کرده؟", why: "کیفیت پاسخ‌های هوش مصنوعی" },
  { q: "چند درصد جواب‌ها مستند بوده؟", why: "نرخ مستندبودن" },
  { q: "چرا fallback زیاد شده؟", why: "بازگشت به موتور قطعی" },
  { q: "هزینه AI چقدر شده؟", why: "هزینه ارائه‌دهنده" },
  { q: "کدام endpoint کند است؟", why: "کارایی مسیرها" },
  { q: "کدام منبع sync نشده؟", why: "وضعیت منابع داده" },
  { q: "چه مشکلاتی نیاز به توجه دارند؟", why: "موارد نیازمند بررسی" },
];

export default function OpsCopilotPage() {
  const { period } = useApp();
  return (
    <Copilot
      heroTitle="از سلامت محصول بپرس"
      heroSub="پاسخ‌ها از تله‌متری واقعی می‌آیند؛ هیچ رخداد، هزینه یا خطایی ساخته نمی‌شود."
      suggestions={PROMPTS}
      placeholder="مثلاً: چرا fallback زیاد شده؟"
      ask={(q) => get<CopilotAnswer>("admin/copilot", { q, f: period.f, t: period.t })}
      onFeedback={(a, useful) => get("admin/copilot/feedback", { intent: a.intent, useful: String(useful) }, "POST").catch(() => {})}
    />
  );
}
