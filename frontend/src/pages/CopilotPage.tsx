import { useRef, useState } from "react";
import type { CopilotAnswer } from "../api";
import { get } from "../api";
import { useApp } from "../ctx";
import { EvBtn, Section } from "../components/ui";

const SUGGESTIONS = [
  "این هفته روی چه تمرکز کنم؟",
  "چرا فروشم کم شد؟",
  "مشتری‌ها چه ساعتی خرید می‌کنند؟",
  "شکست‌های پرداخت بدتر شده؟",
  "تلاش مجدد چقدر فروش برگرداند؟",
  "در مقایسه با همتایان کجا هستم؟",
  "مشتریان تکراری چقدر سهم دارند؟",
];

type Turn = { q: string; a?: CopilotAnswer; pending?: boolean };

export default function CopilotPage() {
  const { merchant, period } = useApp();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  const ask = async (q: string) => {
    if (!q.trim()) return;
    setInput("");
    // capture this turn's index at dispatch so concurrent questions never overwrite each other
    let idx = -1;
    setTurns((t) => { idx = t.length; return [...t, { q, pending: true }]; });
    requestAnimationFrame(() => bottomRef.current?.scrollIntoView({ behavior: "smooth" }));
    let a: CopilotAnswer;
    try {
      a = await get<CopilotAnswer>("copilot", { m: merchant, q, f: period.f, t: period.t });
    } catch {
      a = { answer_fa: "خطا در پردازش پرسش. لطفاً دوباره تلاش کنید.", intent: "error", evidence: [], note_fa: "" };
    }
    setTurns((t) => t.map((x, i) => (i === idx ? { q, a } : x)));
    requestAnimationFrame(() => bottomRef.current?.scrollIntoView({ behavior: "smooth" }));
  };

  return (
    <Section title="از کسب‌وکارت بپرس"
             sub="دستیار قطعی و آفلاین: پاسخ‌ها مستقیم از موتور تحلیلی می‌آیند، نه از مدل زبانی — بنابراین هر عدد قابل ردیابی است.">
      <div className="chat">
        {turns.length === 0 && (
          <div className="empty" style={{ textAlign: "start" }}>
            <b>سوالی بپرسید یا یکی از پیشنهادها را انتخاب کنید</b>
            پاسخ همیشه بر اساس بازه انتخابی شما ({period.label}) محاسبه می‌شود.
          </div>
        )}
        {turns.map((t, i) => (
          <div key={i} style={{ display: "contents" }}>
            <div className="bubble bubble-q">{t.q}</div>
            <div className="bubble bubble-a num" aria-live="polite">
              {t.pending ? "در حال محاسبه…" : (
                <>
                  {t.a!.answer_fa}
                  {t.a!.evidence.length > 0 && (
                    <div style={{ marginTop: 8 }}>
                      <EvBtn title="پاسخ دستیار" items={t.a!.evidence} label="این اعداد از کجا آمدند؟" />
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <div className="suggest" style={{ marginTop: 16 }}>
        {SUGGESTIONS.map((s) => <button key={s} onClick={() => ask(s)}>{s}</button>)}
      </div>

      <form className="ask" onSubmit={(e) => { e.preventDefault(); ask(input); }}>
        <input value={input} onChange={(e) => setInput(e.target.value)}
               placeholder="مثلاً: چرا فروشم کم شد؟" aria-label="پرسش از دستیار" />
        <button className="btn btn-brand" type="submit" disabled={!input.trim()}>بپرس</button>
      </form>
    </Section>
  );
}
