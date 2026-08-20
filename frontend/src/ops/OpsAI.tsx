import type { AdminAI, AdminEval } from "../api";
import { useAdmin } from "../ctx";
import { faNum, pct } from "../fmt";
import { Empty, Loading, Section } from "../components/ui";
import { Term } from "../components/Tooltip";

function Bar({ label, value, tip }: { label: string; value: number | null; tip?: string }) {
  return (
    <div className="dist-row">
      <span className="dist-label">{tip ? <Term label={label} tip={tip} /> : label}</span>
      <span className="dist-track"><span className="dist-fill num" style={{ width: `${Math.round((value ?? 0) * 100)}%` }} /></span>
      <span className="dist-val num">{value == null ? "—" : pct(value)}</span>
    </div>
  );
}

export default function OpsAI() {
  const a = useAdmin<AdminAI>("admin/ai-ops");
  const ev = useAdmin<AdminEval>("admin/ai-eval");
  if (a.loading) return <Loading rows={3} />;
  if (a.error || !a.data) return <Empty title="خطا در دریافت داده هوش مصنوعی" body={a.error ?? ""} />;
  const d = a.data;

  return (
    <>
      <header style={{ marginBottom: 18 }}>
        <h1 style={{ fontSize: "var(--fs-xl)", fontWeight: 800 }}>هوش مصنوعی: عملکرد و هزینه</h1>
        <p style={{ color: "var(--ink-2)", fontSize: "var(--fs-s)" }}>
          آیا هوش مصنوعی کمک می‌کند یا حرف بی‌پایه می‌زند؟ کیفیت، مستندبودن و هزینه — جدا از هم.
        </p>
      </header>

      {!d.has_data ? (
        <Empty title="هنوز فعالیت هوش مصنوعی ثبت نشده"
               body="در حالت آفلاین همه پاسخ‌ها از موتور قطعی می‌آیند (هزینهٔ صفر). با پرسیدن از دستیارِ پذیرنده یا عملیات، این بخش زنده پر می‌شود." />
      ) : (
        <>
          <div className="stats" role="list">
            <div className="stat" role="listitem"><span className="k">کل درخواست‌ها</span><div className="v num">{faNum(d.total)}</div></div>
            <div className="stat" role="listitem"><span className="k">با مدل زبانی</span><div className="v num">{faNum(d.llm_requests)}</div></div>
            <div className="stat" role="listitem">
              <span className="k"><Term label="پاسخ ۹۵٪ (تأخیر)" tip="۹۵٪ درخواست‌های مدل سریع‌تر از این زمان پاسخ گرفته‌اند." /></span>
              <div className="v num">{d.latency_ms?.p95 == null ? "—" : `${faNum(d.latency_ms.p95)} م‌ث`}</div></div>
            <div className="stat" role="listitem"><span className="k">توکن کل</span><div className="v num">{faNum(d.tokens_total)}</div></div>
            <div className="stat" role="listitem"><span className="k">هزینه کل</span><div className="v num">{d.cost_usd_total} $</div></div>
          </div>

          <Section title="کیفیت پاسخ‌ها" sub="مستندبودن یعنی همه اعداد پاسخ از موتور قطعی می‌آیند — مدل زبانی عددی نمی‌سازد.">
            <div className="ops-panel">
              <Bar label="نرخ مستندبودن" value={d.grounded_rate ?? null}
                   tip="سهم پاسخ‌هایی که اعدادشان کاملاً از موتور تحلیلی قطعی می‌آید." />
              <Bar label="پوشش شواهد" value={d.evidence_coverage ?? null}
                   tip="سهم پاسخ‌هایی که دست‌کم یک شاهد قابل‌ردیابی همراه دارند." />
              <Bar label="نرخ بازگشت به موتور قطعی" value={d.fallback_rate ?? null}
                   tip="سهم پاسخ‌هایی که مدل زبانی کنار گذاشته شد و پاسخ قطعی به کاربر رسید (در دسترس‌بودن حفظ می‌شود)." />
              <p className="num" style={{ marginTop: 8, fontSize: "var(--fs-xs)", color: "var(--ink-3)" }}>
                پاسخ بدون شاهد: {faNum(d.zero_evidence)} · رخداد پرریسک (عدد بی‌پشتوانه که رد شد): {faNum(d.hallucination_risk)}
                {d.feedback && d.feedback.total > 0 && ` · بازخورد کاربر: ${faNum(d.feedback.useful)}👍 / ${faNum(d.feedback.not_useful)}👎`}
              </p>
            </div>
          </Section>
        </>
      )}

      <Section title="ارزیابی خودکار دستیار" sub="چهار بُعد جدا از هم — هرگز یک نمرهٔ بی‌معنا. کیفیت زبانی و سودمندی به قضاوت انسانی نیاز دارند.">
        {ev.loading ? <Loading rows={1} /> : ev.data ? (
          <div className="ops-panel">
            <Bar label="درستی تحلیل انتخابی" value={ev.data.indicators.deterministic_correctness}
                 tip="آیا برای هر پرسش، تحلیل/ابزار درست انتخاب شد؟" />
            <Bar label="کیفیت مستندسازی" value={ev.data.indicators.grounding_quality}
                 tip="آیا پاسخ‌ها شاهد قابل‌ردیابی داشتند؟" />
            <Bar label="ایمنی در نبود داده" value={ev.data.indicators.refusal_safety}
                 tip="آیا هنگام کمبود داده به‌جای ساختن عدد، صادقانه امتناع کرد و علیت جعلی نساخت؟" />
            <p className="num" style={{ marginTop: 8, fontSize: "var(--fs-xs)", color: "var(--ink-3)" }}>
              {faNum(ev.data.passed)} از {faNum(ev.data.total)} مورد قبول · کیفیت زبانی و سودمندی کسب‌وکاری: قضاوت انسانی (نمرهٔ خودکار ندارد).
            </p>
          </div>
        ) : <Empty title="ارزیابی در دسترس نیست" body="" />}
      </Section>

      {d.has_data && d.models && d.models.length > 0 && (
        <Section title="مدل‌ها و موضوع پرسش‌ها" sub="کدام مدل و چه نوع پرسش‌هایی بیشتر بوده‌اند.">
          <div className="ops-panel">
            <div className="chips-row">
              {d.models.map((m) => <span key={m.model} className="chip chip-info num">{m.model} · {faNum(m.count)}</span>)}
            </div>
            <div className="chips-row" style={{ marginTop: 8 }}>
              {d.intents?.map((i) => <span key={i.intent} className="chip chip-mute num">{i.intent} · {faNum(i.count)}</span>)}
            </div>
          </div>
        </Section>
      )}
    </>
  );
}
