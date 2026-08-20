import type { AdminPerformance } from "../api";
import { useAdmin } from "../ctx";
import { faNum, pct } from "../fmt";
import { Empty, Loading, Section } from "../components/ui";
import { Term } from "../components/Tooltip";

function ms(v: number | null | undefined) { return v == null ? "—" : `${faNum(v)} م‌ث`; }

export default function OpsPerformance() {
  const p = useAdmin<AdminPerformance>("admin/performance");
  if (p.loading) return <Loading rows={3} />;
  if (p.error || !p.data) return <Empty title="خطا در دریافت کارایی" body={p.error ?? ""} />;
  const d = p.data;

  if (!d.has_data) {
    return (
      <Section title="کارایی محصول" sub="سرعت، پایداری و خطای واقعیِ API — زنده اندازه‌گیری می‌شود.">
        <Empty title="هنوز ترافیکی ثبت نشده" body={d.note_fa ?? "با استفاده از داشبورد، این بخش زنده پر می‌شود."} />
      </Section>
    );
  }
  const L = d.latency_ms!;

  return (
    <>
      <header style={{ marginBottom: 18 }}>
        <h1 style={{ fontSize: "var(--fs-xl)", fontWeight: 800 }}>کارایی محصول</h1>
        <p style={{ color: "var(--ink-2)", fontSize: "var(--fs-s)" }}>آیا زرین‌بین سریع و پایدار است؟ کجا کند می‌شود؟ چه چیزی خطا می‌دهد؟</p>
      </header>

      <div className="stats" role="list">
        <div className="stat" role="listitem"><span className="k">درخواست‌ها</span><div className="v num">{faNum(d.total)}</div></div>
        <div className="stat" role="listitem"><span className="k">توان عبور</span><div className="v num">{faNum(d.throughput_rps)}<span className="u">req/s</span></div></div>
        <div className="stat" role="listitem">
          <span className="k"><Term label="پاسخ نیمی از درخواست‌ها" tip="میانه (p50): نیمی از درخواست‌ها سریع‌تر از این زمان پاسخ گرفته‌اند." /></span>
          <div className="v num">{ms(L.p50)}</div></div>
        <div className="stat" role="listitem">
          <span className="k"><Term label="پاسخ ۹۵٪ درخواست‌ها" tip="یعنی ۹۵ درصد درخواست‌ها سریع‌تر از این زمان پاسخ گرفته‌اند؛ فقط ۵٪ کندتر بوده‌اند." /></span>
          <div className="v num">{ms(L.p95)}</div></div>
        <div className="stat" role="listitem"><span className="k">نرخ خطای سرور</span>
          <div className="v num" style={{ color: (d.error_rate ?? 0) > 0 ? "var(--bad)" : undefined }}>{pct(d.error_rate)}</div></div>
      </div>

      {d.attention && d.attention.length > 0 && (
        <div className="callout" style={{ marginTop: 14 }}>
          <b>نیازمند بررسی: </b>{d.attention.map((a) => a.fa).join(" · ")}
        </div>
      )}

      <Section title="کارایی به تفکیک مسیر" sub="کندترین و پرخطاترین مسیرها بالای جدول‌اند.">
        <div className="ops-panel tbl-wrap">
          <table className="tbl num">
            <thead><tr>
              <th style={{ textAlign: "start" }}>مسیر</th><th>تعداد</th><th>p50</th>
              <th><Term label="p95" tip="۹۵٪ درخواست‌ها سریع‌تر از این." /></th>
              <th><Term label="p99" tip="۹۹٪ درخواست‌ها سریع‌تر از این؛ بدترین حالت‌های کند." /></th>
              <th>خطا</th>
            </tr></thead>
            <tbody>
              {d.endpoints!.map((e) => (
                <tr key={e.path}>
                  <td style={{ direction: "ltr", textAlign: "left", fontFamily: "Consolas, monospace", fontSize: "12px" }}>{e.path}</td>
                  <td>{faNum(e.count)}</td><td>{ms(e.p50)}</td><td>{ms(e.p95)}</td><td>{ms(e.p99)}</td>
                  <td style={{ color: e.error_rate > 0 ? "var(--bad)" : "var(--ink-3)" }}>{pct(e.error_rate)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>
    </>
  );
}
