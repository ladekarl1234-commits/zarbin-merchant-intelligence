import { useEffect, useMemo, useState } from "react";
import { get } from "../api";
import type { AdminOps } from "../api";
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

export default function AdminPage() {
  const [data, setData] = useState<AdminOps | null>(null);
  const [err, setErr] = useState("");
  const [question, setQuestion] = useState("");

  const load = () => get<AdminOps>("admin/ops", {}).then(setData).catch(() => setErr("دریافت وضعیت مرکز کنترل ناموفق بود."));
  useEffect(() => { load(); const id = window.setInterval(load, 15000); return () => window.clearInterval(id); }, []);

  const aiState = useMemo(() => {
    if (!data) return "—";
    if (!data.ai.requests) return "هنوز درخواستی ثبت نشده";
    if ((data.ai.grounded_rate ?? 0) < data.slo.target_ai_grounded_rate) return "نیازمند بررسی";
    return "سالم";
  }, [data]);

  if (err) return <div className="empty">{err}</div>;
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
          <Stat label="هزینه AI" value={`$${data.ai.cost_usd.toFixed(4)}`} hint="در حالت openrouter/free هزینه مدل صفر در نظر گرفته می‌شود؛ هزینه زیرساخت جداگانه محاسبه نشده است." />
        </div>
      </Section>

      <Section title="عملکرد و کیفیت AI" sub="برای اینکه بفهمیم پاسخ‌ها سریع، مستند و قابل اتکا هستند یا نه.">
        <div className="card ops-panel">
          <div className="ops-row"><b>مدل پیش‌فرض</b><span className="num">{data.ai.default_model}</span></div>
          <div className="ops-row"><b>OpenRouter</b><span className={`chip ${data.ai.openrouter_configured ? "chip-good" : "chip-warn"}`}>{data.ai.openrouter_configured ? "متصل" : "بدون کلید؛ fallback فعال"}</span></div>
          <div className="ops-row"><b>تعداد درخواست ثبت‌شده</b><span className="num">{faNum(data.ai.requests)}</span></div>
          <div className="ops-row"><b>P95 زمان پاسخ</b><span className="num">{data.ai.p95_latency_ms == null ? "—" : `${faNum(Math.round(data.ai.p95_latency_ms))} ms`}</span></div>
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

      <Section title="گفت‌وگوی مدیریتی" sub="سوال یا موضوع را با متن یا صدا ثبت کنید. این نسخه برای گفت‌وگوی عملیاتی آماده شده و می‌تواند بعداً به agent تخصصی عملیات متصل شود.">
        <div className="card voice-room">
          <div className="voice-orb" aria-hidden>ز</div>
          <div>
            <b>Voice Mode</b>
            <p>مثلاً بگویید: «چرا fallback زیاد شده؟» یا «کدام منبع داده هنوز وصل نشده؟»</p>
          </div>
          <VoiceInput onText={setQuestion} />
        </div>
        <textarea className="ops-textarea" value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="موضوع گفتگو یا یادداشت مدیریتی…" />
        <p className="subtle">برای جلوگیری از پاسخ‌سازی بی‌پایه، اتصال این بخش به مدل باید از همان لایه evidence-safe عبور کند؛ فعلاً متن/صدا برای تحلیل عملیاتی ثبت می‌شود.</p>
      </Section>
    </>
  );
}
