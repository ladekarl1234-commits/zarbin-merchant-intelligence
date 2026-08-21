import { useEffect, useRef, useState } from "react";
import type { CopilotAnswer } from "../api";
import { ConfChip, EvBtn, IconMic } from "./ui";
import { Term, TIPS } from "./Tooltip";

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
    rec.lang = "fa-IR"; rec.interimResults = true; rec.continuous = false;
    let finalText = "";
    rec.onresult = (e: any) => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        if (r.isFinal) finalText += r[0].transcript; else interim += r[0].transcript;
      }
      onText((finalText + interim).trim());
    };
    rec.onerror = () => setListening(false);
    rec.onend = () => setListening(false);
    recRef.current = rec; setListening(true); rec.start();
  };
  useEffect(() => () => recRef.current?.stop(), []);
  return { supported, listening, toggle };
}

type Turn = { id: number; q: string; a?: CopilotAnswer; pending?: boolean; vote?: boolean };
export type Prompt = { q: string; why?: string };
export type GlanceItem = { k: string; v: string; d?: string; dColor?: string; tip?: keyof typeof TIPS };

export type CopilotProps = {
  heroTitle: string;
  heroSub: string;
  glance?: GlanceItem[];
  suggestions: Prompt[];
  placeholder: string;
  ask: (q: string) => Promise<CopilotAnswer>;
  onFeedback?: (a: CopilotAnswer, useful: boolean) => void;
};

export default function Copilot({ heroTitle, heroSub, glance, suggestions, placeholder, ask, onFeedback }: CopilotProps) {
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
    try { a = await ask(q); }
    catch { a = { answer_fa: "خطا در پردازش پرسش. لطفاً دوباره تلاش کنید.", intent: "error", evidence: [], note_fa: "" }; }
    setTurns((t) => t.map((x) => (x.id === id ? { ...x, a, pending: false } : x)));
    requestAnimationFrame(() => bottomRef.current?.scrollIntoView({ behavior: "smooth" }));
  };
  const vote = (id: number, useful: boolean) => {
    setTurns((t) => t.map((x) => (x.id === id ? { ...x, vote: useful } : x)));
    const turn = turns.find((x) => x.id === id);
    if (turn?.a && onFeedback) onFeedback(turn.a, useful);
  };

  const empty = turns.length === 0;
  return (
    <div className="chat-page">
      {empty && (
        <>
          <div className="chat-hero">
            <h1>{heroTitle}</h1>
            <p>{heroSub}</p>
          </div>
          {glance && glance.length > 0 && (
            <div className="glance" role="list" aria-label="یک نگاه به کسب‌وکار">
              {glance.map((g) => (
                <div className="g" role="listitem" key={g.k}>
                  <div className="gk">{g.tip ? <Term label={g.k} tip={g.tip} /> : g.k}</div>
                  <div className="gv num">{g.v}</div>
                  {g.d && <div className="gd num" style={{ color: g.dColor ?? "var(--ink-3)" }}>{g.d}</div>}
                </div>
              ))}
            </div>
          )}
          <div className="prompt-grid">
            {suggestions.map((p) => (
              <button key={p.q} className="prompt-card" onClick={() => run(p.q)}>
                <div className="pq">{p.q}</div>
                {p.why && <div className="pw">{p.why}</div>}
              </button>
            ))}
          </div>
        </>
      )}

      <div className="chat">
        {turns.map((t) => (
          <div key={t.id} style={{ display: "contents" }}>
            <div className="bubble bubble-q">{t.q}</div>
            {t.pending ? (
              <div className="bubble-pending">در حال محاسبه از داده‌های شما<span className="dots">…</span></div>
            ) : (() => {
              // ZB-032: the copilot used to answer a different question instead of admitting it
              // didn't understand. `fallback` is the current backend intent; `out_of_scope` is the
              // new one it's moving to (handle both). Lead with an explicit admission instead of a
              // confidence chip that implies the (wrong) answer is trustworthy.
              const outOfScope = t.a!.intent === "fallback" || t.a!.intent === "out_of_scope";
              return (
                <div className="bubble bubble-a num" aria-live="polite">
                  {outOfScope && <p style={{ margin: "0 0 6px", fontWeight: 700 }}>سوال شما را دقیق متوجه نشدم.</p>}
                  <p style={{ margin: 0 }}>{t.a!.answer_fa}</p>
                  <div className="ans-badges">
                    {t.a!.source === "llm"
                      ? <span className="chip chip-info">با کمک هوش مصنوعی</span>
                      : <Term label={<span className="src-chip"><span className="dot" />محاسبه قطعی از داده شما</span>} tip="deterministic" />}
                    {t.a!.fallback && <span className="chip chip-warn">پاسخ قطعی جایگزین شد</span>}
                    {!outOfScope && t.a!.confidence && <ConfChip level={t.a!.confidence} />}
                  </div>
                  {outOfScope && suggestions.length > 0 && (
                    <div className="suggest" style={{ marginTop: 10 }}>
                      {suggestions.slice(0, 4).map((p) => (
                        <button key={p.q} type="button" onClick={() => run(p.q)}>{p.q}</button>
                      ))}
                    </div>
                  )}
                  <div className="ans-actions">
                    {t.a!.evidence.length > 0 && <EvBtn title="پاسخ زرین‌بین" items={t.a!.evidence} label="این عدد از کجا آمد؟" />}
                    {onFeedback && (
                      <span className="vote" role="group" aria-label="آیا این پاسخ کمک کرد؟">
                        <button type="button" className={`vote-btn ${t.vote === true ? "on" : ""}`} aria-pressed={t.vote === true} onClick={() => vote(t.id, true)} title="مفید بود">👍</button>
                        <button type="button" className={`vote-btn ${t.vote === false ? "on" : ""}`} aria-pressed={t.vote === false} onClick={() => vote(t.id, false)} title="مفید نبود">👎</button>
                      </span>
                    )}
                  </div>
                </div>
              );
            })()}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <div className="composer">
        <form onSubmit={(e) => { e.preventDefault(); run(input); }}>
          {voice.supported && (
            <button type="button" className={`mic ${voice.listening ? "on" : ""}`} onClick={voice.toggle}
                    aria-pressed={voice.listening} aria-label={voice.listening ? "توقف ضبط صدا" : "با میکروفون بپرسید"}
                    title={voice.listening ? "در حال شنیدن…" : "با میکروفون بپرسید"}>
              <IconMic />
            </button>
          )}
          <input value={input} onChange={(e) => setInput(e.target.value)}
                 placeholder={voice.listening ? "در حال شنیدن… صحبت کنید" : placeholder} aria-label="پرسش از زرین‌بین" />
          <button type="submit" className="composer-send" disabled={!input.trim()}>بپرس</button>
        </form>
        <p className="composer-note">اعداد هرگز توسط هوش مصنوعی ساخته نمی‌شوند؛ همه از موتور تحلیلی قطعی می‌آیند.</p>
      </div>
    </div>
  );
}
