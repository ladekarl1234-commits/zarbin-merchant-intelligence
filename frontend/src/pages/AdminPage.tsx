import { useEffect, useMemo, useState } from "react";
import { get } from "../api";
import type { AdminCopilotAnswer, AdminOps } from "../api";
import { Section } from "../components/ui";
import VoiceInput from "../components/VoiceInput";
import { faNum, pct } from "../fmt";

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="ops-stat">
      <div className="k">{label}{hint ? <span className="term-tip" tabIndex={0} data-tip={hint}>؟</span> : null}</div>
      <div className="v num">{value}</div>
    </div>
  );
}

type OpsTurn = { id: number; q: string; a?: AdminCopilotAnswer; pending?: boolean };

export default function AdminPage() {
  const [data, setData] = useState<AdminOps | null>(null);
  const [err, setErr] = useState("");
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<OpsTurn[]>([]);
  const [seq, setSeq] = useState(0);

  const load = () => get<AdminOps>("admin/ops", {}).then((d) => { setData(d); setErr(""); }).catch(() => setErr("دریافت وضعیت مرکز کنترل ناموفق بود."));
  useEffect(() => { load(); const id = window.setInterval(load, 15000); return () => window.clearInterval(id); }, []);

  const ask = async (q: string) => {
    if (!q.trim()) return;
    const id = seq + 1;
    setSeq(id);
    setQuestion("");
    setTurns((t) => [...t, { id, q, pending: true }]);
    try {
      const a = await get<AdminCopilotAnswer>("admin/copilot", { q });
      setTurns((t) => t.map((x) => x.id === id ? { ...x, a, pending: false } : x));
      load();
    } catch {
      setTurns((t) => t.map((x) => x.id === id ? { ...x, pending: false, a: {
        answer_fa: "پاسخ مدیریتی در دسترس نیست. وضعیت منابع و سرویس را بررسی کنید.", intent: "error",
        ai: { mode: "error", model: "—", fallback: true, grounded: false, latency_ms: 0, cost_usd: 0 },
      } } : x));
    }
  };

  const aiState = useMemo(() => {
    if (!data) return "—";
    if (!data.ai.requests) return "هنوز درخواستی ثبت نشده";
    if ((data.ai.grounded_rate ?? 0) < data.slo.target_ai_grounded_rate) return "نیازمند بررسی";
    return "سالم";
  }, [data]);

  if (err && !data) return <div className="empty">{err}</div>;
  if (!data) return <div className="empty">در حال آماده‌سازی مرکز کنترل…</div>;

  return (
    <>
      <Section title="مرکز کنترل زرین‌بین" sub="نمای مدیریتی و فنی برای عملکرد محصول، کیفیت تحلیل هوشمند، هزینه، سرعت و منابع داده.">
        <div className="ops-hero">
          <div>
            <span className="eyebrow">وضعیت کل سامانه</span>
            <h2>{aiState}</h2>
            <p>این صفحه خودِ موتور تحلیل را پایش می‌کند؛ یعنی فقط کسب‌وکار را نمی‌سنجیم، کیفیت پاسخ‌گویی زرین‌بین را هم می‌سنجیم.</p>
          </div>
          <button className="btn" onClick={load}>به‌روزرسانی</button>
        </div>
        <div className="ops-grid">
          <Stat label="پذیرنده" value={faNum(data.platform.merchants)} />
          <Stat label="جلسه پرداخت" value={faNum(data.platform.sessions)} hint="هر فرایند پرداخت از ساخت لینک تا نتیجه نهایی؛ تلاش مجدد یک جلسه جدید حساب نمی‌شود." />
          <Stat label="نرخ پاسخ مستند" value={data.ai.grounded_rate == null ? "—" : pct(data.ai.grounded_rate)} hint="سهم پاسخ‌های دستیار که حداقل یک شاهد تحلیلی قابل ردیابی دارند." />
          <Stat label="تاخیر متوسط AI" value={data.ai.avg_latency_ms == null ? "—" : `${faNum(Math.round(data.ai.avg_latency_ms))} ms`} hint="زمان از دریافت سوال تا آماده شدن پاسخ؛ شامل fallback داخلی هم می‌شود." />
          <Stat label="Fallback" value={data.ai.fallback_rate == null ? "—" : pct(data.ai.fallback_rate)} hint="وقتی مدل بیرونی در دسترس نیست یا خطا می‌دهد، پاسخ قطعی داخلی جایگزین می‌شود." />
          <Stat label="هزینه AI" value={`$${data.ai.cost_usd.toFixed(4)}`} hint="هزینه مدل ثبت‌شده در Gateway. مسیر رایگان OpenRouter هزینه مدل را صفر نگه می‌دارد؛ هزینه زیرساخت جداست." />
        </div>
      </Section>

      <Section title="عملکرد و کیفیت AI" sub="برای اینکه بفهمیم پاسخ‌ها سریع، مستند و قابل اتکا هستند یا نه.">
        <div className="card ops-panel">
          <div className="ops-row"><b>مدل پیش‌فرض</b><span className="num">{data.ai.default_model}</span></div>
          <div className="ops-row"><b>OpenRouter</b><span className={`chip ${data.ai.openrouter_configured ? "chip-good" : "chip-warn"}`}>{data.ai.openrouter_configured ? "متصل" : "بدون کلید؛ fallback فعال"}</span></div>
          <div className="ops-row"><b>تعداد درخواست ثبت‌شده</b><span className="num">{faNum(data.ai.requests)}</span></div>
          <div className="ops-row"><b>P95 زمان پاسخ <span className="term-tip" tabIndex={0} data-tip="۹۵٪ پاسخ‌ها سریع‌تر از این زمان آماده شده‌اند. این معیار از میانگین برای دیدن کندی‌های واقعی مفیدتر است.">؟</span></b><span className="num">{data.ai.p95_latency_ms == null ? "—" : `${faNum(Math.round(data.ai.p95_latency_ms))} ms`}</span></div>
        </div>
        {data.ai.recent.length ? (
          <div className="card tbl-wrap" style={{ marginTop: 12 }}>
            <table className="tbl">
              <thead><tr><th>زمان</th><th>حالت</th><th>مدل</th><th>قصد</th><th>تاخیر</th><th>مستند</th><th>Fallback</th></tr></thead>
              <tbody>{data.ai.recent.slice(0, 12).map((r, i) => (
                <tr key={`${r.ts}-${i}`}><td className="num">{new Date(r.ts).toLocaleTimeString("fa-IR")}</td><td>{r.mode}</td><td className="num">{r.model}</td><td>{r.intent}</td><td className="num">{faNum(Math.round(r.latency_ms))} ms</td><td>{r.grounded ? "بله" : "خیر"}</td><td>{r.fallback ? "بله" : "خیر"}</td></tr>
              ))}</tbody>
            </table>
          </div>
        ) : <div className="empty">پس از اولین گفت‌وگو، جزئیات عملکرد AI اینجا ظاهر می‌شود.</div>}
      </Section>

      <Section title="منابع داده" sub="هسته به منبع خاصی قفل نشده؛ هر منبع از طریق Adapter وارد می‌شود و وضعیتش مستقل دیده می‌شود.">
        <div className="source-list">
          {data.sources.map((s) => (
            <div className="source-item card" key={s.id}>
              <div><b>{s.label}</b><p>{s.detail}</p></div>
              <span className={`chip ${s.configured ? "chip-good" : "chip-mute"}`}>{s.configured ? "آماده" : "نیازمند تنظیم"}</span>
            </div>
          ))}
        </div>
        {data.ga4 ? <div className="card ops-panel" style={{ marginTop: 12 }}><b>آخرین snapshot گوگل آنالیتیکس</b><p className="num">{data.ga4.period.from} → {data.ga4.period.to} · {faNum(data.ga4.totals.sessions)} session</p></div> : null}
      </Section>

      <Section title="بینش منابع جدید" sub="داده بیرونی فقط نمایش داده نمی‌شود؛ ابتدا با قواعد قابل بازتولید تحلیل می‌شود و بعد می‌تواند توسط AI به زبان ساده توضیح داده شود.">
        {data.source_insights.length ? <div className="source-insights">{data.source_insights.map((i) => (
          <article className="card source-insight" key={i.id}>
            <span className="eyebrow">{i.source.toUpperCase()}</span><h3>{i.title_fa}</h3><p>{i.observation_fa}</p>
            <div className="insight-action"><b>پیشنهاد:</b> {i.action_fa}</div><small>{i.caveat_fa}</small>
          </article>
        ))}</div> : <div className="empty">پس از اتصال و همگام‌سازی Google Analytics، تغییرات معنادار منبع به‌صورت خودکار به insight تبدیل می‌شوند.</div>}
      </Section>

      <Section title="گفت‌وگوی مدیریتی" sub="با متن یا صدا درباره کیفیت AI، سرعت، هزینه و منابع داده گفتگو کنید. پاسخ از telemetry واقعی شروع می‌شود؛ مدل بیرونی فقط همان شواهد را توضیح می‌دهد.">
        <div className="card voice-room">
          <div className="voice-orb" aria-hidden>ز</div>
          <div><b>Voice Mode</b><p>مثلاً بگویید: «چرا fallback زیاد شده؟»، «سرعت جواب‌ها چطوره؟» یا «کدام منبع هنوز وصل نشده؟»</p></div>
          <VoiceInput onText={setQuestion} />
        </div>
        {turns.length ? <div className="ops-chat">{turns.map((t) => (
          <div key={t.id} className="ops-turn"><div className="ops-q">{t.q}</div><div className="ops-a">{t.pending ? "در حال بررسی وضعیت…" : <>{t.a?.answer_fa}<div className="ai-meta"><span>{t.a?.ai.model}</span><span>{Math.round(t.a?.ai.latency_ms ?? 0)} ms</span>{t.a?.ai.fallback ? <span className="chip chip-warn">fallback</span> : <span className="chip chip-good">مستند</span>}</div></>}</div></div>
        ))}</div> : null}
        <form className="ops-ask" onSubmit={(e) => { e.preventDefault(); ask(question); }}>
          <VoiceInput onText={setQuestion} compact />
          <textarea className="ops-textarea" value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="موضوع گفتگو…" aria-label="پرسش مدیریتی" />
          <button className="btn btn-brand" type="submit" disabled={!question.trim()}>گفتگو</button>
        </form>
      </Section>
    </>
  );
}
