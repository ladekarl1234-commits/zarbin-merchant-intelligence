import { useRef, useState } from "react";

type SpeechResultEvent = { results: ArrayLike<{ 0: { transcript: string }; isFinal: boolean }> };
type RecognitionLike = {
  lang: string; interimResults: boolean; continuous: boolean;
  start: () => void; stop: () => void;
  onresult: ((e: SpeechResultEvent) => void) | null;
  onend: (() => void) | null;
  onerror: (() => void) | null;
};
type RecognitionCtor = new () => RecognitionLike;

declare global {
  interface Window {
    SpeechRecognition?: RecognitionCtor;
    webkitSpeechRecognition?: RecognitionCtor;
  }
}

export default function VoiceInput({ onText, compact = false }: { onText: (text: string) => void; compact?: boolean }) {
  const [listening, setListening] = useState(false);
  const ref = useRef<RecognitionLike | null>(null);
  const Ctor = window.SpeechRecognition ?? window.webkitSpeechRecognition;

  if (!Ctor) {
    return compact ? null : <span className="voice-unavailable">ورودی صوتی در این مرورگر پشتیبانی نمی‌شود.</span>;
  }

  const toggle = () => {
    if (listening && ref.current) {
      ref.current.stop();
      return;
    }
    const r = new Ctor();
    ref.current = r;
    r.lang = "fa-IR";
    r.interimResults = true;
    r.continuous = false;
    r.onresult = (e) => {
      let text = "";
      for (let i = 0; i < e.results.length; i += 1) text += e.results[i][0].transcript;
      if (text.trim()) onText(text.trim());
    };
    r.onend = () => setListening(false);
    r.onerror = () => setListening(false);
    setListening(true);
    r.start();
  };

  return (
    <button type="button" className={`voice-btn ${listening ? "is-listening" : ""}`} onClick={toggle}
            aria-pressed={listening} aria-label={listening ? "توقف دریافت صدا" : "گفتن سوال با صدا"}>
      <span aria-hidden>{listening ? "■" : "●"}</span>
      {compact ? null : (listening ? "در حال شنیدن…" : "گفتن با صدا")}
    </button>
  );
}
