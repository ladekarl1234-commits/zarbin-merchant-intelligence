import type { Peers } from "../api";
import { useData } from "../ctx";
import { faNum, pct } from "../fmt";
import { PercentileRow } from "../components/charts";
import { Empty, EvBtn, Loading, Section } from "../components/ui";
import { Term } from "../components/Tooltip";

const METRIC_FA: Record<string, { name: string; hint: string }> = {
  conv: { name: "نرخ تبدیل نهایی", hint: "سهم جلسه‌هایی که به پرداخت موفق رسید" },
  first_try_conv: { name: "موفقیت در اولین تلاش", hint: "بدون نیاز به تلاش دوباره" },
  no_attempt_rate: { name: "انصراف پیش از پرداخت", hint: "مشتری به درگاه نرسید (کمتر بهتر)" },
  inbank_abandon_rate: { name: "رهاشدن در بانک", hint: "به بانک رسید اما کامل نشد (کمتر بهتر)" },
  recovery_rate: { name: "بازیابی پس از شکست اول", hint: "نجات با تلاش دوباره" },
};

export default function PeersPage() {
  const pe = useData<Peers>("peers");
  if (pe.loading) return <Loading rows={3} />;
  if (pe.error || !pe.data) return <Empty title="خطا در دریافت داده" body={pe.error ?? ""} />;
  const d = pe.data;

  return (
    <>
      <Section title={<Term label="مقایسه با همتایان" tip="peers" />} sub="مقایسه فقط با پذیرندگانی که واقعاً شبیه شما هستند — نه میانگین کل بازار.">
        <div className="card" style={{ padding: 20, marginBottom: 18 }}>
          <h3 style={{ fontSize: "var(--fs-m)", marginBottom: 6 }}>چرا این پذیرندگان همتای شما هستند؟</h3>
          <p style={{ fontSize: "var(--fs-s)", color: "var(--ink-2)" }}>{d.group.rule_fa}</p>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 10 }}>
            <span className="chip chip-info num">{faNum(d.group.n)} پذیرنده همتا</span>
            <span className="chip chip-mute">{String(d.group.me.category_title ?? "")}</span>
            <span style={{ marginInlineStart: "auto" }}>
              <EvBtn title="گروه همتایان" items={[d.evidence]} label="روش انتخاب همتایان" />
            </span>
          </div>
        </div>

        {!d.group.sufficient ? (
          <Empty title="همتای کافی وجود ندارد"
                 body="برای معیارگیری معتبر دست‌کم ۵ پذیرنده قابل مقایسه با فعالیت کافی در این دوره لازم است. به جای عدد نامطمئن، این مقایسه نمایش داده نمی‌شود." />
        ) : (
          <div style={{ display: "grid", gap: 14 }}>
            {d.rows.map((r) => {
              const m = METRIC_FA[r.metric];
              if (r.suppressed || r.percentile == null) {
                return (
                  <div className="card" style={{ padding: "16px 20px" }} key={r.metric}>
                    <b>{r.metric === "conv" ? <Term label={m.name} tip="conv" /> : m.name}</b>
                    <p style={{ fontSize: "var(--fs-s)", color: "var(--ink-3)" }}>داده کافی برای این مقایسه وجود ندارد.</p>
                  </div>
                );
              }
              const strong = r.percentile >= 60;
              const weak = r.percentile <= 40;
              return (
                <div className="card" style={{ padding: "16px 20px", display: "grid", gap: 10 }} key={r.metric}>
                  <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
                    <b>{r.metric === "conv" ? <Term label={m.name} tip="conv" /> : m.name}</b>
                    <span style={{ fontSize: "var(--fs-xs)", color: "var(--ink-3)" }}>{m.hint}</span>
                    <span className={`chip ${strong ? "chip-good" : weak ? "chip-bad" : "chip-mute"} num`} style={{ marginInlineStart: "auto" }}>
                      بهتر از {faNum(r.percentile)}٪ از {faNum(r.n_peers!)} همتا
                    </span>
                    {r.low_n && (
                      <span className="chip chip-warn" style={{ fontSize: "var(--fs-xs)" }}>
                        گروه کوچک — با احتیاط
                      </span>
                    )}
                  </div>
                  <PercentileRow percentile={r.percentile} />
                  <div style={{ display: "flex", gap: 16, fontSize: "var(--fs-xs)", color: "var(--ink-2)", flexWrap: "wrap" }} className="num">
                    <span>شما: <b>{pct(r.value)}</b></span>
                    <span>میانه همتایان: {pct(r.p50)}</span>
                    <span>چارک برتر: {pct(r.higher_better ? r.p75 : r.p25)}</span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Section>
    </>
  );
}
