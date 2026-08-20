import { useMemo } from "react";
import type { Changes } from "../api";
import { get } from "../api";
import { useApp } from "../ctx";
import { faDate, faNum, pct, pp, rial } from "../fmt";
import { Waterfall } from "../components/charts";
import { Empty, EvBtn, Loading, Section } from "../components/ui";
import { useEffect, useState } from "react";

const DRIVER_FA: Record<string, string> = {
  no_attempt_rate: "انصراف پیش از پرداخت",
  inbank_abandon_rate: "رهاشدن در بانک",
  failed_bank_rate: "خطای صریح بانکی",
  paid_unverified_rate: "پرداخت تاییدنشده",
  reversed_rate: "برگشت‌خورده",
};

export default function ChangesPage() {
  const { merchant, period } = useApp();
  const [state, setState] = useState<{ data: Changes | null; loading: boolean; error: string | null }>({ data: null, loading: true, error: null });

  const windows = useMemo(() => {
    // integer-day midpoint, matching the backend insight card (zarin/insights._change_alert)
    // so the Changes page and the "GMV change" insight quote the same split.
    const f = new Date(period.f + "T12:00:00");
    const t = new Date(period.t + "T12:00:00");
    const spanDays = Math.round((t.getTime() - f.getTime()) / 86400000);
    const mid = new Date(f.getTime() + Math.floor(spanDays / 2) * 86400000);
    const mid2 = new Date(mid.getTime() + 86400000);
    const iso = (x: Date) => x.toISOString().slice(0, 10);
    return { f1: period.f, t1: iso(mid), f2: iso(mid2), t2: period.t };
  }, [period]);

  useEffect(() => {
    if (!merchant) return;
    let alive = true;
    setState((s) => ({ ...s, loading: true }));
    get<Changes>("changes", { m: merchant, ...windows })
      .then((d) => alive && setState({ data: d, loading: false, error: null }))
      .catch((e) => alive && setState({ data: null, loading: false, error: String(e) }));
    return () => { alive = false; };
  }, [merchant, windows]);

  if (state.loading) return <Loading rows={3} />;
  if (state.error || !state.data) return <Empty title="خطا در دریافت داده" body={state.error ?? ""} />;
  const d = state.data;
  const rel = d.before.gmv ? d.delta_gmv / d.before.gmv : null;

  return (
    <Section title="چه چیزی تغییر کرد؟"
             sub="مقایسه نیمه اول و نیمه دوم بازه انتخابی، با تجزیه دقیق ریاضی (LMDI) — سهم سه عامل دقیقاً برابر کل تغییر است.">
      <div className="card" style={{ padding: 20, marginBottom: 18 }}>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "baseline" }}>
          <span style={{ fontSize: "var(--fs-s)", color: "var(--ink-2)" }} className="num">
            {faDate(d.before.from)} تا {faDate(d.before.to)} ← {faDate(d.after.from)} تا {faDate(d.after.to)}
          </span>
          <span style={{ marginInlineStart: "auto" }}>
            <EvBtn title="تجزیه تغییر فروش" items={[d.evidence]} label="روش محاسبه" />
          </span>
        </div>
        <p style={{ fontSize: "var(--fs-xl)", fontWeight: 800, marginTop: 8 }} className="num">
          فروش موفق {d.delta_gmv >= 0 ? "رشد" : "افت"}{" "}
          <span style={{ color: d.delta_gmv >= 0 ? "var(--good)" : "var(--bad)" }}>
            {rial(Math.abs(d.delta_gmv))}{rel != null ? ` (${pct(Math.abs(rel))})` : ""}
          </span>
        </p>
        <p style={{ fontSize: "var(--fs-s)", color: "var(--ink-2)" }} className="num">
          {rial(d.before.gmv)} ← {rial(d.after.gmv)}
        </p>
      </div>

      {!d.decomposable ? (
        <Empty title="تجزیه ممکن نیست"
               body="برای تجزیه، هر دو نیمه باید فروش موفق داشته باشند. یکی از دوره‌ها خالی است." />
      ) : (
        <>
          <div className="card" style={{ padding: 20, marginBottom: 18 }}>
            <h3 style={{ fontSize: "var(--fs-m)", marginBottom: 12 }}>سهم هر عامل در تغییر فروش</h3>
            <Waterfall total={d.delta_gmv} items={[
              { label: "تعداد جلسه‌ها", value: d.contrib.sessions ?? 0 },
              { label: "نرخ تبدیل", value: d.contrib.conv ?? 0 },
              { label: "مبلغ متوسط", value: d.contrib.ticket ?? 0 },
            ]} />
            <div className="tbl-wrap" style={{ marginTop: 14 }}>
              <table className="tbl num">
                <thead><tr><th>عامل</th><th>نیمه اول</th><th>نیمه دوم</th></tr></thead>
                <tbody>
                  <tr><td>جلسه‌های پرداخت</td><td>{faNum(d.before.sessions)}</td><td>{faNum(d.after.sessions)}</td></tr>
                  <tr><td>نرخ تبدیل</td><td>{pct(d.before.conv)}</td><td>{pct(d.after.conv)}</td></tr>
                  <tr><td>مبلغ متوسط تراکنش</td><td>{rial(d.before.ticket)}</td><td>{rial(d.after.ticket)}</td></tr>
                </tbody>
              </table>
            </div>
          </div>

          {Object.keys(d.conv_drivers).length > 0 && (
            <div className="card" style={{ padding: 20 }}>
              <h3 style={{ fontSize: "var(--fs-m)", marginBottom: 4 }}>ریشه تغییر نرخ تبدیل</h3>
              <p style={{ fontSize: "var(--fs-s)", color: "var(--ink-2)", marginBottom: 12 }}>
                هر عدد نشان می‌دهد آن حالت چقدر روی نرخ تبدیل اثر گذاشته (مثبت = به نفع تبدیل).
                مجموع این اثرها دقیقاً برابر کل تغییر نرخ تبدیل است.
              </p>
              <div className="tbl-wrap">
                <table className="tbl num">
                  <thead><tr><th>عامل</th><th>اثر بر نرخ تبدیل</th></tr></thead>
                  <tbody>
                    {Object.entries(d.conv_drivers).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1])).map(([k, v]) => (
                      <tr key={k}>
                        <td>{DRIVER_FA[k] ?? k}</td>
                        <td style={{ color: v >= 0 ? "var(--good)" : "var(--bad)", fontWeight: 700 }}>{pp(v)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </Section>
  );
}
