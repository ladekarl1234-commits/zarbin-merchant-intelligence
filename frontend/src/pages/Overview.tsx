import type { InsightCard as Card, Overview as Ov } from "../api";
import { useApp, useData } from "../ctx";
import { deltaPct, faNum, pct, rial } from "../fmt";
import InsightCard from "../components/InsightCard";
import { TrendChart } from "../components/charts";
import { Empty, EvBtn, Loading, Section } from "../components/ui";

function Delta({ cur, prev, goodUp = true }: { cur: number | null; prev: number | null | undefined; goodUp?: boolean }) {
  if (prev == null) return null;
  const d = deltaPct(cur, prev);
  if (d == null) return null;
  const good = d >= 0 === goodUp;
  return (
    <span className={`d num ${good ? "" : ""}`} style={{ color: good ? "var(--good)" : "var(--bad)" }}>
      {d >= 0 ? "▲" : "▼"} {pct(Math.abs(d))} نسبت به دوره قبل
    </span>
  );
}

export default function Overview() {
  const { period, meta, merchant } = useApp();
  const ov = useData<Ov>("overview", { cf: period.cf, ct: period.ct });
  const ins = useData<{ cards: Card[] }>("insights");

  if (ov.loading) return <Loading rows={3} />;
  if (ov.error || !ov.data) return <Empty title="خطا در دریافت داده" body={ov.error ?? ""} />;
  const k = ov.data.kpis;
  const p = ov.data.previous;
  const cat = meta?.merchants.find((m) => m.merchant_key === merchant)?.category_title;

  return (
    <>
      <header style={{ marginBottom: 20 }}>
        <h1 style={{ fontSize: "var(--fs-xl)", fontWeight: 800 }}>
          سلام، پذیرنده <span className="num">{merchant}</span>
        </h1>
        <p style={{ color: "var(--ink-2)", fontSize: "var(--fs-s)" }}>
          {cat} · {period.label} · هر عدد این صفحه با دکمه «محاسبه» تا داده خام قابل ردیابی است.
        </p>
      </header>

      <div className="stats" role="list" aria-label="شاخص‌های کلیدی">
        <div className="stat" role="listitem">
          <span className="k">فروش موفق <EvBtn title="فروش موفق" items={[ov.data.evidence.gmv]} sampleOutcome="verified" label="" /></span>
          <div className="v num">{rial(k.gmv, false)}<span className="u">ریال</span></div>
          <Delta cur={k.gmv} prev={p?.gmv} />
        </div>
        <div className="stat" role="listitem">
          <span className="k">پرداخت موفق <EvBtn title="پرداخت‌های موفق" items={[ov.data.evidence.gmv]} sampleOutcome="verified" label="" /></span>
          <div className="v num">{faNum(k.verified)}</div>
          <Delta cur={k.verified} prev={p?.verified} />
        </div>
        <div className="stat" role="listitem">
          <span className="k">نرخ تبدیل <EvBtn title="نرخ تبدیل" items={[ov.data.evidence.conv]} label="" /></span>
          <div className="v num">{pct(k.conv)}</div>
          <Delta cur={k.conv} prev={p?.conv} />
        </div>
        <div className="stat" role="listitem">
          <span className="k">میانه مبلغ تراکنش <EvBtn title="میانه مبلغ تراکنش" items={[ov.data.evidence.median_ticket]} sampleOutcome="verified" label="" /></span>
          <div className="v num">{rial(k.median_ticket, false)}<span className="u">ریال</span></div>
        </div>
        <div className="stat" role="listitem">
          <span className="k">مشتریان پرداخت‌کننده <EvBtn title="مشتریان" items={[ov.data.evidence.customers]} sampleOutcome="verified" label="" /></span>
          <div className="v num">{faNum(k.customers)}</div>
        </div>
      </div>

      {k.paid_unverified > 0 && (
        <div className="callout" style={{ marginTop: 14, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <b className="num">{faNum(k.paid_unverified)} پرداخت به مبلغ {rial(k.paid_unverified_amount)}</b>
          تسویه شده اما هنوز از سمت شما تایید (Verify) نشده است.
          <EvBtn title="پرداخت‌های تاییدنشده" items={[ov.data.evidence.paid_unverified]} sampleOutcome="paid_unverified" label="جزئیات" />
        </div>
      )}

      <Section title="مهم‌ترین فرصت‌های شما" sub="رتبه‌بندی بر اساس اثر مالی × اطمینان ÷ زحمت اجرا. فقط مواردی که شواهد کافی دارند نمایش داده می‌شوند.">
        {ins.loading ? <Loading rows={2} /> : !ins.data?.cards.length ? (
          <Empty title="فرصت قابل اتکایی پیدا نشد"
                 body="در این دوره هیچ شکاف معناداری نسبت به همتایان یا خط پایه خودتان دیده نمی‌شود — این خودش خبر خوبی است." />
        ) : (
          <div style={{ display: "grid", gap: 14 }}>
            {ins.data.cards.slice(0, 4).map((c, i) => <InsightCard key={c.id} card={c} rank={i + 1} />)}
          </div>
        )}
      </Section>

      <Section title="روند روزانه فروش موفق" sub="جمع مبلغ جلسه‌های Verified به تفکیک روز؛ هر جلسه فقط یک بار شمرده می‌شود.">
        <div className="card" style={{ padding: "18px 10px 8px" }}>
          {ov.data.daily.length ? <TrendChart daily={ov.data.daily} /> :
            <Empty title="داده‌ای نیست" body="در این بازه جلسه‌ای ثبت نشده است." />}
        </div>
      </Section>
    </>
  );
}
