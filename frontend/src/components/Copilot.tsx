import { useEffect, useRef, useState } from "react";
import type { CopilotAnswer } from "../api";
import { ConfChip, EvBtn, IconMic, Section } from "./ui";

/** Persian voice-to-text via the Web Speech API, with graceful fallback when absent. */
function useVoice(onText: (t: string) => void) {
  const [listening, setListening] = useState(false);
  const recRef = useRef<any>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const SR = typeof window !== "undefined" ? (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition : null;
  const supported = !!SR;

  const toggle = () => {
    if (!supported) return;
    if (listening) { recRef.current?.stop(); return; }
    const rec = new SR();
    rec.lang = "fa-IR";
    rec.interimResults = true;
    rec.continuous = false;
    let finalText = "";
    rec.onresult = (e: any) => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        if (r.isFinal) finalText += r[0].transcript;
        else interim += r[0].transcript;
      }
      onText((finalText + interim).trim());
    };
    rec.onerror = () => setListening(false);
    rec.onend = () => setListening(false);
    recRef.current = rec;
    setListening(true);
    rec.start();
  };

  useEffect(() => () => recRef.current?.stop(), []);
  return { supported, listening, toggle };
}

type Turn = { id: number; q: string; a?: CopilotAnswer; pending?: boolean; vote?: boolean };

export type CopilotProps = {
  title: string;
  sub: string;
  suggestions: string[];
  placeholder: string;
  emptyHint: string;
  ask: (q: string) => Promise<CopilotAnswer>;
  onFeedback?: (a: CopilotAnswer, useful: boolean) => void;
  accent?: "brand" | "ops";
};

function SourceBadge({ a }: { a: CopilotAnswer }) {
  return (
    <div className="ans-badges">
      {a.source === "llm" ? (
        <span className="chip chip-info">با کمک هوش مصنوعی</span>
      ) : (
        <span className="chip chip-mute">موتور تحلیلی قطعی</span>
      )}
      {a.fallback && <span className="chip chip-warn">پاسخ قطعی جایگزین شد</span>}
      {a.confidence && <ConfChip level={a.confidence} />}
    </div>
  );
}

export default function Copilot({ title, sub, suggestions, placeholder, emptyHint, ask, onFeedback, accent = "brand" }: CopilotProps) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const seq = useRef(0);
  const bottomRef = useRef<HTMLDivElement>(null);
  const voice = useVoice(setInput);

  const run = async (q: string) => {
    if (!q.trim()) return;
    setInput("");
    const id = ++seq.current;
    setTurns((t) => [...t, { id, q, pending: true }]);
    requestAnimationFrame(() => bottomRef.current?.scrollIntoView({ behavior: "smooth" }));
    let a: CopilotAnswer;
    try {
      a = await ask(q);
    } catch {
      a = { answer_fa: "خطا در پردازش پرسش. لطفاً دوباره تلاش کنید.", intent: "error", evidence: [], note_fa: "" };
    }
    setTurns((t) => t.map((x) => (x.id === id ? { ...x, a, pending: false } : x)));
    requestAnimationFrame(() => bottomRef.current?.scrollIntoView({ behavior: "smooth" }));
  };

  const vote = (id: number, useful: boolean) => {
    setTurns((t) => t.map((x) => (x.id === id ? { ...x, vote: useful } : x)));
    const turn = turns.find((x) => x.id === id);
    if (turn?.a && onFeedback) onFeedback(turn.a, useful);
  };

  return (
    <Section title={title} sub={sub}>
      <div className="chat">
        {turns.length === 0 && (
          <div className="empty" style={{ textAlign: "start" }}>
            <b>سوالی بپرسید یا یکی از پیشنهادها را انتخاب کنید</b>
            {emptyHint}
          </div>
        )}
        {turns.map((t) => (
          <div key={t.id} style={{ display: "contents" }}>
            <div className="bubble bubble-q">{t.q}</div>
            <div className="bubble bubble-a num" aria-live="polite">
              {t.pending ? "در حال محاسبه…" : (
                <>
                  {t.a!.answer_fa}
                  <SourceBadge a={t.a!} />
                  <div className="ans-actions">
                    {t.a!.evidence.length > 0 && (
                      <EvBtn title="پاسخ دستیار" items={t.a!.evidence} label="این اعداد از کجا آمدند؟" />
                    )}
                    {onFeedback && (
                      <span className="vote" role="group" aria-label="آیا این پاسخ کمک کرد؟">
                        <button type="button" className={`vote-btn ${t.vote === true ? "on" : ""}`}
                                aria-pressed={t.vote === true} onClick={() => vote(t.id, true)} title="مفید بود">👍</button>
                        <button type="button" className={`vote-btn ${t.vote === false ? "on" : ""}`}
                                aria-pressed={t.vote === false} onClick={() => vote(t.id, false)} title="مفید نبود">👎</button>
                      </span>
                    )}
                  </div>
                </>
              )}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <div className="suggest" style={{ marginTop: 16 }}>
        {suggestions.map((s) => <button key={s} onClick={() => run(s)}>{s}</button>)}
      </div>

      <form className="ask" onSubmit={(e) => { e.preventDefault(); run(input); }}>
        {voice.supported && (
          <button type="button" className={`mic ${voice.listening ? "on" : ""}`} onClick={voice.toggle}
                  aria-pressed={voice.listening} aria-label={voice.listening ? "توقف ضبط صدا" : "صحبت کنید"}
                  title={voice.listening ? "در حال شنیدن…" : "با میکروفون بپرسید"}>
            <IconMic />
          </button>
        )}
        <input value={input} onChange={(e) => setInput(e.target.value)}
               placeholder={voice.listening ? "در حال شنیدن… صحبت کنید" : placeholder} aria-label="پرسش از دستیار" />
        <button className={`btn ${accent === "ops" ? "btn-ops" : "btn-brand"}`} type="submit" disabled={!input.trim()}>بپرس</button>
      </form>
    </Section>
  );
}
