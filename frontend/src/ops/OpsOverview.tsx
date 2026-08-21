import { useState } from "react";
import type { AdminPlatform } from "../api";
import { useApp, useAdmin } from "../ctx";
import { faNum, pct, rial } from "../fmt";
import { Empty, Loading, Section } from "../components/ui";

const SEV: Record<string, string> = { high: "chip-bad", medium: "chip-warn", low: "chip-mute" };

// ZB-026: Control Center had no way to drill down from platform-level KPIs to the merchants
// behind them. Contract (may 404 until the backend agent ships it — handled gracefully below).
type MerchantRow = {
  merchant_key: string; category_title: string; sessions: number; gmv: number;
  paid_unverified_amount: number; paid_unverified: number; no_attempt_rate: number | null; recovered_gmv: number;
};
type MerchantsResp = { rows: MerchantRow[] };
const SORTS: { id: string; label: string }[] = [
  { id: "unverified", label: "تاییدنشده" },
  { id: "no_attempt", label: "بدون اقدام" },
  { id: "gmv", label: "فروش موفق" },
  { id: "recovered", label: "بازیابی‌شده" },
];

export default function OpsOverview() {
  const { period } = useApp();
  const p = useAdmin<AdminPlatform>("admin/platform", { usePeriod: true });
  const [sort, setSort] = useState<string>("gmv");
  const merchants = useAdmin<MerchantsResp>("admin/merchants", { usePeriod: true, extra: { sort, limit: "20" } });

  if (p.loading) return <Loading rows={3} />;
  if (p.error || !p.data) return <Empty title="خطا در دریافت داده پلتفرم" body={p.error ?? ""} />;
  const k = p.data.kpis;
  const totalCatGmv = p.data.categories.reduce((s, c) => s + (c.gmv ?? 0), 0) || 1;

  return (
    <>
      <header style={{ marginBottom: 18 }}>
        <h1 style={{ fontSize: "var(--fs-xl)", fontWeight: 800 }}>سلامت پلتفرم زرین‌بین</h1>
        <p style={{ color: "var(--ink-2)", fontSize: "var(--fs-s)" }}>
          این صفحه می‌گوید «خودِ محصول» چطور کار می‌کند، نه یک کسب‌وکار خاص · بازه {period.label}
        </p>
      </header>

      <div className="kpi-grid" role="list" aria-label="شاخص‌های پلتفرم">
        <div className="kpi" role="listitem"><span className="k">پذیرندگان فعال</span>
          <div className="v num">{faNum(k.active_merchants)}<span className="u">از {faNum(k.total_merchants)}</span></div></div>
        <div className="kpi" role="listitem"><span className="k">جلسه‌های پرداخت</span>
          <div className="v num">{faNum(k.sessions)}</div></div>
        <div className="kpi" role="listitem"><span className="k">فروش موفق کل</span>
          <div className="v num">{rial(k.gmv, false)}<span className="u">ریال</span></div></div>
        <div className="kpi" role="listitem"><span className="k">نرخ تبدیل کل</span>
          <div className="v num">{pct(k.conv)}</div></div>
        <div className="kpi" role="listitem"><span className="k">تسویه‌شدهٔ تاییدنشده</span>
          <div className="v num">{rial(k.paid_unverified_amount, false)}<span className="u">ریال</span></div></div>
        <div className="kpi" role="listitem"><span className="k">نجات با تلاش مجدد</span>
          <div className="v num">{rial(k.recovered_gmv, false)}<span className="u">ریال</span></div></div>
      </div>

      <Section title="چه چیزی الان ارزش توجه دارد؟" sub="سیگنال‌های سطح پلتفرم که به تصمیم منجر می‌شوند — نه فقط عدد.">
        {p.data.insights.length === 0 ? (
          <Empty title="موردی برای توجه فوری نیست" body="هیچ سیگنال پرریسکی در این بازه دیده نمی‌شود." />
        ) : (
          <div style={{ display: "grid", gap: 12 }}>
            {p.data.insights.map((it) => (
              <div key={it.title_fa} className="ops-card">
                <div className="ops-card-head">
                  <span className={`chip ${SEV[it.severity] ?? "chip-mute"}`}>
                    {it.severity === "high" ? "بالا" : it.severity === "medium" ? "متوسط" : "پایین"}
                  </span>
                  <b>{it.title_fa}</b>
                </div>
                <p className="num" style={{ color: "var(--ink-2)", fontSize: "var(--fs-s)" }}>{it.body_fa}</p>
                <p style={{ fontSize: "var(--fs-s)" }}><b>اقدام: </b>{it.action_fa}</p>
              </div>
            ))}
          </div>
        )}
      </Section>

      <Section title="توزیع فروش بین دسته‌ها" sub="تمرکز درآمد پلتفرم روی کدام صنف‌هاست.">
        <div className="ops-panel">
          {p.data.categories.map((c) => (
            <div key={c.category} className="dist-row">
              <span className="dist-label">{c.category}</span>
              <span className="dist-track"><span className="dist-fill num"
                style={{ width: `${Math.max(2, ((c.gmv ?? 0) / totalCatGmv) * 100)}%` }} /></span>
              <span className="dist-val num">{rial(c.gmv, false)}</span>
            </div>
          ))}
        </div>
        <p className="num" style={{ marginTop: 10, fontSize: "var(--fs-xs)", color: "var(--ink-3)" }}>
          تمرکز: ۵ پذیرندهٔ برتر {pct(p.data.concentration.top5_share)} از فروش موفق · ناهنجاری‌ها:
          {" "}{faNum(p.data.anomalies.reversed_sessions)} جلسهٔ Reversed، {faNum(p.data.anomalies.verified_wo_ok_try)} جلسهٔ موفق بدون تلاش موفق (مستند در کیفیت داده).
        </p>
      </Section>

      <Section title="پذیرندگان" sub="پذیرندگانی که بیشترین نیاز به پیگیری یا بیشترین سهم را دارند.">
        <div className="seg" role="group" aria-label="ترتیب فهرست پذیرندگان" style={{ marginBottom: 10 }}>
          {SORTS.map((s) => (
            <button key={s.id} aria-pressed={s.id === sort} onClick={() => setSort(s.id)}>{s.label}</button>
          ))}
        </div>
        <div className="card tbl-wrap">
          {merchants.loading ? <Loading rows={2} /> : merchants.error || !merchants.data?.rows.length ? (
            <Empty title="فهرست پذیرندگان در دسترس نیست" body={merchants.error ?? "داده‌ای برای این بازه و ترتیب یافت نشد."} />
          ) : (
            <table className="tbl num">
              <thead>
                <tr>
                  <th>پذیرنده</th><th>صنف</th><th>جلسه‌ها</th><th>فروش موفق</th>
                  <th>تسویه‌شده تاییدنشده</th><th>انصراف پیش از پرداخت</th><th>نجات با تلاش مجدد</th>
                </tr>
              </thead>
              <tbody>
                {merchants.data.rows.map((r) => (
                  <tr key={r.merchant_key}>
                    <td>{r.merchant_key}</td>
                    <td>{r.category_title}</td>
                    <td>{faNum(r.sessions)}</td>
                    <td>{rial(r.gmv, false)}</td>
                    <td>{rial(r.paid_unverified_amount, false)}
                      <span style={{ color: "var(--ink-3)" }}> ({faNum(r.paid_unverified)})</span>
                    </td>
                    <td>{pct(r.no_attempt_rate)}</td>
                    <td>{rial(r.recovered_gmv, false)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </Section>
    </>
  );
}
