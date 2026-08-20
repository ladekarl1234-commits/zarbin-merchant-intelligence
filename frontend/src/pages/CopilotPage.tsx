import { useRef, useState } from "react";
import type { CopilotAnswer } from "../api";
import { get } from "../api";
import { useApp } from "../ctx";
import { EvBtn, Section } from "../components/ui";
import VoiceInput from "../components/VoiceInput";

const SUGGESTIONS = [
  "این هفته روی چه تمرکز کنم؟",
  "چرا فروشم کم شد؟",
  "مشتری‌ها چه ساعتی خرید می‌کنند؟",
  "شکست‌های پرداخت بدتر شده؟",
  "تلاش مجدد چقدر فروش برگرداند؟",
  "در مقایسه با همتایان کجا هستم؟",
  "مشتریان تکراری چقدر سهم دارند؟",
];

type Turn = { id: number; q: string; a?: CopilotAnswer; pending?: boolean };

export default function CopilotPage() {
  const { merchant, period } = useApp();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const seq = useRef(0);
  const bottomRef = useRef<HTMLDivElement>(null);

  const ask = async (q: string) => {
    if (!q.trim()) return;
    setInput("");
    const id = ++seq.current;
    setTurns((t) => [...t, { id, q, pending: true }]);
    requestAnimationFrame(() => bottomRef.current?.scrollIntoView({ behavior: "smooth" }));
    let a: CopilotAnswer;
    try {
      a = await get<CopilotAnswer>("copilot", { m: merchant, q, f: period.f, t: period.t });
    } catch {
      a = { answer_fa: "خطا در پردازش پرسش. لطفاً دوباره تلاش کنید.", intent: "error", evidence: [], note_fa: "" };
    }
    setTurns((t) => t.map((x) => (x.id === id ? { ...x, a, pending: false } : x)));
    requestAnimationFrame(() => bottomRef.current?.scrollIntoView({ behavior: "smooth" }));
  };

  return (
    <Section title="از کسب‌وکارت بپرس"
             sub="عددها همیشه از موتور تحلیلی می‌آیند. اگر OpenRouter فعال باشد، مدل فقط همان شواهد را به زبان ساده توضیح می‌دهد؛ اگر در دسترس نباشد، پاسخ داخلی ادامه می‌دهد.">
      <div className="voice-room merchant-voice">
        <div className="voice-orb" aria-hidden>ز</div>
        <div><b>Voice Mode</b><p>سوالت را بگو؛ متنش خودکار وارد می‌شود و قبل از ارسال قابل ویرایش است.</p></div>
        <VoiceInput onText={setInput} />
      </div>

      <div className="chat">
        {turns.length === 0 && (
          <div className="empty" style={{ textAlign: "start" }}>
            <b>سوالی بپرسید یا یکی از پیشنهادها را انتخاب کنید</b>
            پاسخ همیشه بر اساس بازه انتخابی شما ({period.label}) محاسبه می‌شود.
          </div>
        )}
        {turns.map((t) => (
          <div key={t.id} style={{ display: "contents" }}>
            <div className="bubble bubble-q">{t.q}</div>
            <div className="bubble bubble-a num" aria-live="polite">
              {t.pending ? "در حال محاسبه…" : (
                <>
                  {t.a!.answer_fa}
                  {t.a?.ai ? (
                    <div className="ai-meta">
                      <span className={`chip ${t.a.ai.fallback ? "chip-warn" : "chip-good"}`}>
                        {t.a.ai.mode === "openrouter" ? "توضیح AI + شواهد" : "تحلیل داخلی"}
                      </span>
                      <span className="term-tip" tabIndex={0} data-tip="مدل اجازه ندارد عدد تازه بسازد؛ عددها از موتور تحلیلی و شواهد همین پذیرنده می‌آیند.">پاسخ مستند</span>
                      <span>{Math.round(t.a.ai.latency_ms)} ms</span>
                    </div>
                  ) : null}
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
        <VoiceInput onText={setInput} compact />
        <input value={input} onChange={(e) => setInput(e.target.value)}
               placeholder="مثلاً: چرا فروشم کم شد؟" aria-label="پرسش از دستیار" />
        <button className="btn btn-brand" type="submit" disabled={!input.trim()}>بپرس</button>
      </form>
    </Section>
  );
}
