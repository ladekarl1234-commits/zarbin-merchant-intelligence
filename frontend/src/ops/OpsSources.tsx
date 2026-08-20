import type { AdminSources } from "../api";
import { useApp, useAdmin } from "../ctx";
import { localizeDates } from "../fmt";
import { Empty, Loading, Section } from "../components/ui";

const STATUS: Record<string, [string, string]> = {
  ok: ["chip-good", "متصل"],
  not_configured: ["chip-mute", "تنظیم‌نشده"],
  error: ["chip-bad", "خطا"],
};

export default function OpsSources() {
  const { period } = useApp();
  const s = useAdmin<AdminSources>("admin/sources", { usePeriod: true });
  if (s.loading) return <Loading rows={2} />;
  if (s.error || !s.data) return <Empty title="خطا در دریافت منابع" body={s.error ?? ""} />;

  return (
    <>
      <header style={{ marginBottom: 18 }}>
        <h1 style={{ fontSize: "var(--fs-xl)", fontWeight: 800 }}>منابع داده</h1>
        <p style={{ color: "var(--ink-2)", fontSize: "var(--fs-s)" }}>
          دیتاست چالش یک ورودی است، نه کل سیستم. منابع آینده از همین‌جا اضافه می‌شوند · بازه {period.label}
        </p>
      </header>

      <div className="callout callout-info">
        <b>حقیقت پرداخت ≠ سیگنال وب.</b> فروش و نرخ تبدیل فقط از منبع پرداخت (زرین‌پال) می‌آیند.
        منابعی مانند گوگل‌آنالیتیکس سیگنال ترافیک/رفتارند و هرگز سطر‌به‌سطر با پرداخت ادغام نمی‌شوند.
      </div>

      <div className="src-grid" style={{ marginTop: 16 }}>
        {s.data.sources.map((src) => {
          const [cls, label] = STATUS[src.status] ?? ["chip-mute", src.status];
          return (
            <div key={src.id} className={`ops-card ${src.is_truth ? "src-truth" : ""}`}>
              <div className="ops-card-head" style={{ justifyContent: "space-between" }}>
                <b>{src.name_fa}</b>
                <span className={`chip ${cls}`}>{label}</span>
              </div>
              <div className="chips-row">
                <span className="chip chip-mute">{src.kind === "payment" ? "پرداخت" : src.kind === "web_analytics" ? "تحلیل وب" : src.kind}</span>
                {src.is_truth && <span className="chip chip-good">منبع حقیقت مالی</span>}
              </div>
              <p style={{ color: "var(--ink-2)", fontSize: "var(--fs-s)" }}>{src.note_fa}</p>
              {src.freshness && (
                <p className="num" style={{ fontSize: "var(--fs-xs)", color: "var(--ink-3)" }}>
                  تازگی داده: {localizeDates(src.freshness.slice(0, 10))}
                </p>
              )}
              {src.id === "ga4" && src.status !== "ok" && (
                <p className="num" style={{ fontSize: "var(--fs-xs)", color: "var(--ink-3)", direction: "ltr", textAlign: "left" }}>
                  اتصال: GA4_PROPERTY_ID + GOOGLE_APPLICATION_CREDENTIALS
                </p>
              )}
            </div>
          );
        })}
      </div>

      <Section title="بینش‌های میان‌منبعی" sub="وقتی یک منبع تحلیل وب متصل شود، رابطهٔ ترافیک→پرداخت (بدون ادعای علیت) اینجا ظاهر می‌شود.">
        {s.data.cross_source_insights.length === 0 ? (
          <Empty title="هنوز بینش میان‌منبعی نیست" body={s.data.cross_source_note_fa ?? ""} />
        ) : (
          <div style={{ display: "grid", gap: 12 }}>
            {s.data.cross_source_insights.map((c) => (
              <div key={c.id} className="ops-card">
                <b>{c.title_fa}</b>
                <p className="num" style={{ color: "var(--ink-2)", fontSize: "var(--fs-s)" }}>{c.observation_fa}</p>
                <p style={{ fontSize: "var(--fs-s)" }}><b>اقدام: </b>{c.action_fa}</p>
                <p style={{ fontSize: "var(--fs-xs)", color: "var(--ink-3)" }}>{c.caveat_fa}</p>
              </div>
            ))}
          </div>
        )}
      </Section>
    </>
  );
}
