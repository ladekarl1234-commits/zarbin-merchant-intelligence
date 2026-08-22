import { useEffect, useState } from "react";
import type { Quality } from "../api";
import { get } from "../api";
import { faNum, pct, rial } from "../fmt";
import { Empty, Loading, Section } from "../components/ui";

const OUTCOME_FA: Record<string, string> = {
  verified: "موفق (Verified)", paid_unverified: "تسویه بدون تایید (Paid)",
  no_attempt: "بدون اقدام (NoAttempt)", abandoned_inbank: "رها در بانک (InBank)",
  failed_bank: "خطای صریح (Failed)", reversed: "برگشت‌خورده (Reversed)",
};

export default function QualityPage() {
  const [d, setD] = useState<Quality | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { get<Quality>("quality", {}).then(setD).catch((e) => setErr(String(e))); }, []);
  if (err) return <Empty title="خطا" body={err} />;
  if (!d) return <Loading rows={3} />;
  const total = d.outcomes.reduce((s, o) => s + o.n, 0);

  return (
    <>
      <Section title="کیفیت داده و صداقت تحلیلی"
               sub="آنچه این محصول می‌تواند و نمی‌تواند از داده نتیجه بگیرد — بدون ترمیم پنهان، بدون عدد ساختگی.">
        {/* Every figure on this page is DATASET-WIDE, not this merchant's. Without saying so,
            a merchant reads «۱٬۰۲۵٬۶۵۵ جلسهٔ موفق» as their own — and the numbers do not change
            when they switch merchant or period, which makes the misreading worse rather than
            self-correcting. The page's subject is the honesty of the data underneath the whole
            product, so its scope belongs on the page. Per-merchant outcome counts are on the
            Funnel page, and this now says so. */}
        <div className="card" style={{ padding: "12px 16px", marginBottom: 14,
                                       borderInlineStart: "3px solid var(--brand)" }}>
          <p style={{ margin: 0, fontSize: "var(--fs-s)", color: "var(--ink-2)" }}>
            <b>محدودهٔ این صفحه: کل دیتاست</b> — همهٔ پذیرنده‌ها و کل بازه؛ نه کسب‌وکار شما و نه بازهٔ
            انتخاب‌شده. این‌جا نشان می‌دهیم دادهٔ زیربنایی محصول چه کیفیتی دارد. همین تفکیک برای
            کسب‌وکار خودتان در صفحهٔ «قیف پرداخت» است.
          </p>
        </div>
        <div className="card tbl-wrap" style={{ marginBottom: 18 }}>
          <table className="tbl num">
            <caption style={{ captionSide: "top", textAlign: "start", padding: "10px 14px 0",
                              fontSize: "var(--fs-xs)", color: "var(--ink-3)" }}>
              توزیع وضعیت نهایی جلسه‌ها — کل دیتاست
            </caption>
            <thead><tr><th>وضعیت نهایی جلسه</th><th>تعداد</th><th>سهم</th><th>مبلغ</th></tr></thead>
            <tbody>
              {d.outcomes.map((o) => (
                <tr key={o.outcome}>
                  <td>{OUTCOME_FA[o.outcome] ?? o.outcome}</td>
                  <td>{faNum(o.n)}</td>
                  <td>{pct(o.n / total)}</td>
                  <td>{o.amount != null ? rial(o.amount) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="grid-2" style={{ marginBottom: 18 }}>
          <div className="card" style={{ padding: 20 }}>
            <h3 style={{ fontSize: "var(--fs-m)" }}>تمرکز بازار</h3>
            <p style={{ fontSize: "var(--fs-s)", color: "var(--ink-2)", marginTop: 6 }} className="num">
              ۵ پذیرنده برتر <b>{pct(d.concentration.top5)}</b> از کل فروش موفق دیتاست را می‌سازند؛ به همین دلیل
              مقایسه با «میانگین کل» گمراه‌کننده است و این محصول فقط با همتایان هم‌مقیاس مقایسه می‌کند.
            </p>
          </div>
          <div className="card" style={{ padding: 20 }}>
            <h3 style={{ fontSize: "var(--fs-m)" }}>ناهنجاری‌های شناخته‌شده</h3>
            <p style={{ fontSize: "var(--fs-s)", color: "var(--ink-2)", marginTop: 6 }} className="num">
              {faNum(d.anomalies.verified_wo_ok_try)} جلسه Verified بدون تلاش موفق ثبت‌شده و{" "}
              {faNum(d.anomalies.reversed_sessions)} جلسه Reversed در داده وجود دارد. این‌ها اصلاح نشده‌اند؛ فقط مستند شده‌اند.
            </p>
          </div>
        </div>

        <div className="card" style={{ padding: 20 }}>
          <h3 style={{ fontSize: "var(--fs-m)", marginBottom: 10 }}>قواعد تحلیلی این محصول</h3>
          <ul style={{ margin: 0, paddingInlineStart: 20, display: "grid", gap: 8, fontSize: "var(--fs-s)", color: "var(--ink-2)" }}>
            {d.rules_fa.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        </div>
      </Section>
    </>
  );
}
