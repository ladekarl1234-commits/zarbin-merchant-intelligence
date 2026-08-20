import type { CopilotAnswer } from "../api";
import { get } from "../api";
import { useApp } from "../ctx";
import Copilot from "../components/Copilot";

const SUGGESTIONS = [
  "وضعیت کل سیستم چطوره؟",
  "AI امروز چطور عمل کرده؟",
  "چند درصد جواب‌ها مستند بوده؟",
  "چرا fallback زیاد شده؟",
  "کدام مدل بیشتر استفاده شده؟",
  "هزینه AI چقدر شده؟",
  "کدام endpoint کند است؟",
  "کدام منبع sync نشده؟",
  "چه مشکلاتی نیاز به توجه دارند؟",
];

export default function OpsCopilotPage() {
  const { period } = useApp();
  return (
    <Copilot
      title="دستیار عملیات"
      sub="از سلامت خودِ محصول بپرسید. پاسخ‌ها از تله‌متری واقعی می‌آیند؛ هیچ رخداد، هزینه یا خطایی ساخته نمی‌شود."
      suggestions={SUGGESTIONS}
      placeholder="مثلاً: چرا fallback زیاد شده؟"
      emptyHint="پاسخ بر پایهٔ داده و تله‌متری زندهٔ پلتفرم است."
      accent="ops"
      ask={(q) => get<CopilotAnswer>("admin/copilot", { q, f: period.f, t: period.t })}
      onFeedback={(a, useful) =>
        get("admin/copilot/feedback", { intent: a.intent, useful: String(useful) }, "POST").catch(() => {})}
    />
  );
}
