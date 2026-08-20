import type { Customers } from "../api";
import { useApp, useData } from "../ctx";
import { faNum, pct, rial } from "../fmt";
import { CohortGrid } from "../components/charts";
import { Empty, EvBtn, Loading, Section } from "../components/ui";

export default function CustomersPage() {
  const { meta } = useApp();
  const cu = useData<Customers>("customers");
  if (cu.loading) return <Loading rows={4} />;
  if (cu.error || !cu.data) return <Empty title="خطا در دریافت داده" body={cu.error ?? ""} />;
  const d = cu.data;
  const s = d.summary;
  const repeatTxnShare = s.txns ? s.repeat_txns / s.txns : null;
  const repeatGmvShare = s.gmv ? s.repeat_gmv / s.gmv : null;
  const repeatCustShare = s.customers ? s.repeat_customers / s.customers : null;

  if (!s.customers) {
    return <Empty title="هنوز داده مشتری کافی نیست"
                  body="در این بازه پرداخت موفقی ثبت نشده است؛ تحلیل مشتری فقط پرداخت‌کنندگان موفق را می‌بیند." />;
  }

  return (
    <>
      <div className="callout callout-info" style={{ marginBottom: 18 }}>{meta?.notes.customer}</div>
      {d.low_n && (
        <div className="callout" style={{ marginBottom: 18 }}>
          تعداد مشتریان این پذیرنده کم است؛ نرخ‌ها و تمرکز و کوهورت زیر ممکن است نویزی باشند و با احتیاط تفسیر شوند.
        </div>
      )}

      <div className="stats">
        <div className="stat">
          <span className="k">مشتریان این دوره <EvBtn title="مشتریان" items={[d.evidence.customers]} label="" /></span>
          <div className="v num">{faNum(s.customers)}</div>
          <span className="d num" style={{ color: "var(--ink-3)" }}>{faNum(s.new_customers)} مشتری جدید</span>
        </div>
        <div className="stat">
          <span className="k">سهم تراکنش مشتریان تکراری <EvBtn title="سهم مشتریان تکراری" items={[d.evidence.repeat]} label="" /></span>
          <div className="v num">{pct(repeatTxnShare)}</div>
          <span className="d num" style={{ color: "var(--ink-3)" }}>{pct(repeatCustShare)} از مشتریان</span>
        </div>
        <div className="stat">
          <span className="k">سهم فروش مشتریان تکراری</span>
          <div className="v num">{pct(repeatGmvShare)}</div>
        </div>
        <div className="stat">
          <span className="k">میانه فاصله بین دو خرید <span className="chip chip-mute" style={{ fontSize: 9 }}>کل بازه</span></span>
          <div className="v num">{d.interval.median_days != null ? `${faNum(Math.round(d.interval.median_days))}` : "—"}<span className="u">روز</span></div>
        </div>
      </div>

      {repeatTxnShare != null && repeatCustShare != null && repeatTxnShare > repeatCustShare && (
        <p style={{ marginTop: 14, fontSize: "var(--fs-s)", color: "var(--ink-2)", maxWidth: "72ch" }}>
          یعنی <b className="num">{pct(repeatCustShare)}</b> از مشتریان شما <b className="num">{pct(repeatTxnShare)}</b> از
          تراکنش‌ها و <b className="num">{pct(repeatGmvShare)}</b> از فروش را می‌سازند — نگه‌داشتن مشتری فعلی از جذب مشتری جدید ارزان‌تر است.
        </p>
      )}

      <Section title="بازگشت مشتریان (کوهورت ماهانه)"
               sub="روی کل بازه داده محاسبه می‌شود (نه فقط دوره انتخابی). هر ردیف: مشتریانی که اولین خرید موفقشان در آن ماه بود؛ ستون‌های بعدی سهم بازگشت آن‌ها در ماه‌های بعد.">
        {d.cohorts.length >= 2 ? (
          <div className="card" style={{ padding: 18 }}>
            <CohortGrid cohorts={d.cohorts} />
          </div>
        ) : (
          <Empty title="هنوز تاریخچه کافی نیست"
                 body="برای تحلیل بازگشت، دست‌کم دو ماه فعالیت لازم است." />
        )}
      </Section>

      <div className="grid-2">
        <Section title="تمرکز مشتری" sub="وابستگی فروش این دوره به مشتریان برتر.">
          <div className="card" style={{ padding: 20 }}>
            {d.concentration.n >= 20 ? (
              <>
                <p style={{ fontSize: "var(--fs-s)" }}>
                  ۵ مشتری برتر <b className="num" style={{ fontSize: "var(--fs-l)" }}>{pct(d.concentration.top5_share)}</b> از فروش موفق این دوره را ساخته‌اند.
                </p>
                <div style={{ marginTop: 8 }}>
                  <EvBtn title="تمرکز مشتری" items={[d.evidence.concentration]} label="نحوه محاسبه" />
                </div>
              </>
            ) : <Empty title="نمونه کوچک" body="با کمتر از ۲۰ مشتری، عدد تمرکز گمراه‌کننده است." />}
          </div>
        </Section>

        <Section title="مشتریان ارزشمند غیرفعال" sub="مشتریانی با ۳ خرید موفق یا بیشتر که بیش از ۳۰ روز است برنگشته‌اند.">
          <div className="card" style={{ padding: 20 }}>
            {d.dormant.n > 0 ? (
              <p style={{ fontSize: "var(--fs-s)" }}>
                <b className="num" style={{ fontSize: "var(--fs-l)" }}>{faNum(d.dormant.n)}</b> مشتری با مجموع خرید تاریخی{" "}
                <b className="num">{rial(d.dormant.gmv)}</b> — بهترین هدف برای کمپین بازگشت.
              </p>
            ) : <Empty title="موردی نیست" body="مشتری پرتکراری که اخیراً غیبت کرده باشد پیدا نشد." />}
          </div>
        </Section>
      </div>
    </>
  );
}
