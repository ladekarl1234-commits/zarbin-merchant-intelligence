import type { Funnel } from "../api";
import { useData } from "../ctx";
import { faNum, pct, rial } from "../fmt";
import { FunnelViz, HourHeat } from "../components/charts";
import { Empty, EvBtn, Loading, Section } from "../components/ui";

const OUTCOME_META: [string, string, string, string][] = [
  ["verified", "تایید نهایی", "chip-good", "verified"],
  ["paid_unverified", "تسویه‌شده بدون تایید", "chip-warn", "paid_unverified"],
  ["no_attempt", "بدون اقدام به پرداخت", "chip-mute", "no_attempt"],
  ["abandoned_inbank", "رهاشده در بانک", "chip-bad", "abandoned_inbank"],
  ["failed_bank", "خطای صریح بانکی", "chip-bad", "failed_bank"],
];

export default function FunnelPage() {
  const fu = useData<Funnel>("funnel");
  if (fu.loading) return <Loading rows={4} />;
  if (fu.error || !fu.data) return <Empty title="خطا در دریافت داده" body={fu.error ?? ""} />;
  const d = fu.data;
  const total = d.stages[0]?.n || 1;

  return (
    <>
      <Section title="قیف پرداخت" sub="مسیر هر جلسه از ایجاد تا تایید نهایی. «بدون اقدام» یعنی مشتری هرگز به درگاه نرسید — این با خطای بانکی فرق دارد.">
        <div className="card" style={{ padding: 20 }}>
          <FunnelViz stages={d.stages} />
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 14, alignItems: "center" }}>
            {OUTCOME_META.map(([key, label, cls]) => (
              <span className={`chip ${cls} num`} key={key}>
                {label}: {faNum(d.outcomes[key] ?? 0)} ({pct((d.outcomes[key] ?? 0) / total)})
              </span>
            ))}
            <span style={{ marginInlineStart: "auto" }}>
              <EvBtn title="قیف پرداخت" items={[d.evidence.funnel]} label="نحوه محاسبه" />
            </span>
          </div>
        </div>
      </Section>

      <div className="grid-2">
        <Section title="اولین تلاش در برابر نتیجه نهایی"
                 sub="فاصله این دو عدد یعنی مشتریانی که فقط با تلاش دوباره نجات پیدا کردند.">
          <div className="card" style={{ padding: 20, display: "grid", gap: 12 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
              <span>موفقیت در همان تلاش اول</span>
              <b className="num" style={{ fontSize: "var(--fs-l)" }}>{pct(d.rates.first_try_conv)}</b>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
              <span>موفقیت نهایی (با تلاش‌های بعدی)</span>
              <b className="num" style={{ fontSize: "var(--fs-l)" }}>{pct(d.rates.conv)}</b>
            </div>
            <hr style={{ border: 0, borderTop: "1px solid var(--line)" }} />
            <p style={{ fontSize: "var(--fs-s)", color: "var(--ink-2)" }}>
              از <b className="num">{faNum(d.recovery.first_fail_pool)}</b> جلسه با تلاش اولِ ناموفق،{" "}
              <b className="num">{faNum(d.recovery.recovered)}</b> جلسه ({pct(d.recovery.recovery_rate)}) در نهایت موفق شد و{" "}
              <b className="num">{rial(d.recovery.recovered_gmv)}</b> فروش نجات یافت.
            </p>
            <span><EvBtn title="بازیابی با تلاش مجدد" items={[d.evidence.recovery]} label="نحوه محاسبه" /></span>
          </div>
        </Section>

        <Section title="نرخ تبدیل بر اساس مبلغ" sub="پنجک‌های مبلغ فقط از جلسه‌های خود شما ساخته می‌شوند تا مقایسه منصفانه باشد.">
          <div className="card tbl-wrap">
            {d.amount_bands.length ? (
              <table className="tbl num">
                <thead><tr><th>بازه مبلغ (ریال)</th><th>جلسه‌ها</th><th>نرخ تبدیل</th></tr></thead>
                <tbody>
                  {d.amount_bands.map((b) => (
                    <tr key={b.band}>
                      <td>{rial(b.lo, false)} تا {rial(b.hi, false)}</td>
                      <td>{faNum(b.sessions)}</td>
                      <td>
                        <span className={`chip ${d.rates.conv != null && b.conv >= d.rates.conv ? "chip-good" : "chip-mute"}`}>{pct(b.conv)}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : <Empty title="نمونه کافی نیست" body="برای تفکیک مبلغی حداقل ۳۰ جلسه در هر بازه لازم است." />}
            <div style={{ padding: "8px 14px" }}>
              <EvBtn title="نرخ تبدیل بر اساس مبلغ" items={[d.evidence.amount_bands]} label="نحوه محاسبه" />
            </div>
          </div>
        </Section>
      </div>

      <Section title="ساعت‌های پرداخت" sub="حجم جلسه‌ها در شبانه‌روز؛ برای زمان‌بندی کمپین و پشتیبانی.">
        <div className="card" style={{ padding: 20 }}>
          <HourHeat hours={d.hours} />
        </div>
      </Section>

      <div className="grid-2">
        <Section title="عملکرد درگاه‌های پرداخت (PSP)" sub="نرخ موفقیت تلاش‌ها روی ترافیک خود شما. انتخاب PSP سمت زرین‌پال است؛ اگر شکاف بزرگ است با پشتیبانی مطرح کنید.">
          <div className="card tbl-wrap">
            {d.psp.length ? (
              <table className="tbl num">
                <thead><tr><th>درگاه</th><th>تلاش‌ها</th><th>نرخ موفقیت تلاش</th></tr></thead>
                <tbody>
                  {d.psp.map((p) => (
                    <tr key={p.psp_code}>
                      <td style={{ direction: "ltr", textAlign: "start" }}>{p.psp_code}</td>
                      <td>{faNum(p.attempts)}</td>
                      <td>{pct(p.ok_rate)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : <Empty title="نمونه کافی نیست" body="برای مقایسه درگاه‌ها حداقل ۳۰ تلاش لازم است." />}
          </div>
        </Section>

        <Section title="پرتکرارترین کدهای خطا" sub="کد پاسخ سوییچ برای تلاش‌های ناموفقی که کد ثبت کرده‌اند.">
          <div className="card tbl-wrap">
            {d.fail_codes.length ? (
              <table className="tbl num">
                <thead><tr><th>کد</th><th>تعداد</th></tr></thead>
                <tbody>
                  {d.fail_codes.map((c) => (
                    <tr key={c.code}>
                      <td style={{ direction: "ltr", textAlign: "start" }}>{c.code}</td>
                      <td>{faNum(c.n)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : <Empty title="کدی ثبت نشده" body="اکثر شکست‌ها بدون کد پاسخ سوییچ هستند (رها شدن در صفحه بانک)." />}
          </div>
        </Section>
      </div>
    </>
  );
}
