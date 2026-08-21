import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { faDateShort, faNum, pct, rial } from "../fmt";
import { Term } from "./Tooltip";

const INK = "#1c1c22";
const YELLOW = "#ffd900";

export function TrendChart({ daily }: { daily: { d: string; gmv: number; conv: number | null }[] }) {
  const data = daily.map((r) => ({ ...r, label: faDateShort(r.d) }));
  return (
    <div style={{ height: 240 }} dir="ltr" role="img" aria-label="روند روزانه فروش موفق">
      <ResponsiveContainer>
        <AreaChart data={data} margin={{ top: 8, right: 8, left: 8, bottom: 0 }}>
          <defs>
            <linearGradient id="g1" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={YELLOW} stopOpacity={0.55} />
              <stop offset="100%" stopColor={YELLOW} stopOpacity={0.05} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="#e4e4e7" vertical={false} />
          <XAxis dataKey="label" tick={{ fontSize: 11, fontFamily: "Vazirmatn" }} tickLine={false}
                 axisLine={{ stroke: "#e4e4e7" }} minTickGap={40} reversed />
          <YAxis tick={{ fontSize: 11, fontFamily: "Vazirmatn" }} tickLine={false} axisLine={false}
                 tickFormatter={(v: number) => rial(v, false)} width={70} orientation="right" />
          <Tooltip
            contentStyle={{ fontFamily: "Vazirmatn", fontSize: 12, direction: "rtl", borderRadius: 10, border: "1px solid #e4e4e7" }}
            formatter={(v) => [rial(v as number), "فروش موفق"]}
            labelFormatter={(l) => `روز ${l}`}
          />
          <Area type="monotone" dataKey="gmv" stroke={INK} strokeWidth={2} fill="url(#g1)" name="فروش موفق"
                isAnimationActive={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export function FunnelViz({ stages }: { stages: { id: string; label_fa: string; n: number }[] }) {
  const max = stages[0]?.n || 1;
  return (
    <div role="table" aria-label="قیف پرداخت">
      {stages.map((s, i) => (
        <div className="funnel-stage" key={s.id} role="row">
          <span role="rowheader" style={{ fontSize: "var(--fs-s)", fontWeight: 600 }}>
            {i === 0 ? <Term label={s.label_fa} tip="sessions" /> : s.label_fa}
          </span>
          <div className="funnel-bar" role="cell" aria-hidden>
            <div className="funnel-fill" style={{ transform: `scaleX(${Math.max(s.n / max, 0.004)})`, width: "100%" }} />
          </div>
          <span role="cell" className="num" style={{ fontSize: "var(--fs-s)", fontWeight: 700, minWidth: 84, textAlign: "start" }}>
            {faNum(s.n)}
            <span style={{ color: "var(--ink-3)", fontWeight: 400 }}> ({pct(s.n / max, 0)})</span>
          </span>
        </div>
      ))}
    </div>
  );
}

export function HourHeat({ hours }: { hours: { hour: number; sessions: number; verified: number }[] }) {
  const byHour = new Map(hours.map((h) => [h.hour, h]));
  const max = Math.max(...hours.map((h) => h.sessions), 1);
  return (
    <div>
      <div className="heat" role="img" aria-label="توزیع جلسه‌ها در ساعت‌های شبانه‌روز">
        {Array.from({ length: 24 }, (_, h) => {
          const r = byHour.get(h);
          const conv = r && r.sessions ? r.verified / r.sessions : null;
          const alpha = r ? 0.12 + 0.88 * (r.sessions / max) : 0.06;
          return (
            <div key={h} title={`ساعت ${h}: ${faNum(r?.sessions ?? 0)} جلسه، تبدیل ${pct(conv)}`}
                 style={{ display: "flex", flexDirection: "column", gap: 3 }}>
              <div className="cell" style={{ background: `rgb(28 28 34 / ${alpha})` }} />
              <span style={{ fontSize: 9, color: "var(--ink-3)", textAlign: "center" }}>{h}</span>
            </div>
          );
        })}
      </div>
      <div className="heat-legend">
        <span>تیره‌تر = جلسه‌های بیشتر</span>
        <span>·</span>
        <span>ساعت‌ها به وقت ثبت جلسه</span>
      </div>
    </div>
  );
}

export function PercentileRow(p: { percentile: number }) {
  // percentile = share of peers this merchant beats (direction-adjusted server-side).
  // Track: good end is LEFT (gradient to left) → position from left = 100 − percentile.
  const pos = 100 - p.percentile;
  return (
    <div style={{ display: "grid", gap: 5 }}>
      <div className="pct-track" dir="ltr">
        <div className="pct-band" style={{ left: "25%", right: "25%", opacity: 0.5, borderRadius: 999 }} />
        <div className="pct-marker" style={{ left: `calc(${pos}% - 9px)`, translate: "0 -50%", top: "50%", position: "absolute" }} />
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: "var(--fs-xs)", color: "var(--ink-3)" }}>
        <span>ضعیف‌تر از همتایان</span>
        <span>بهتر از همتایان</span>
      </div>
    </div>
  );
}

export function Waterfall({ items, total }: { items: { label: string; value: number }[]; total: number }) {
  const max = Math.max(...items.map((i) => Math.abs(i.value)), Math.abs(total), 1);
  return (
    <div role="table" aria-label="سهم عوامل در تغییر فروش">
      {items.map((it) => (
        <div className="wf-row" key={it.label} role="row">
          <span role="rowheader" style={{ fontWeight: 600 }}>{it.label}</span>
          <div className="wf-track" dir="ltr" role="cell" aria-hidden>
            <div className="wf-bar" style={{
              background: it.value >= 0 ? "var(--good)" : "var(--bad)",
              left: it.value >= 0 ? "50%" : `${50 - (Math.abs(it.value) / max) * 48}%`,
              width: `${(Math.abs(it.value) / max) * 48}%`,
            }} />
            <div style={{ position: "absolute", left: "50%", top: 0, bottom: 0, width: 1, background: "var(--line-strong)" }} />
          </div>
          <span role="cell" className="num" style={{ fontWeight: 700, color: it.value >= 0 ? "var(--good)" : "var(--bad)", minWidth: 110, textAlign: "start" }}>
            {it.value >= 0 ? "+" : "−"}{rial(Math.abs(it.value))}
          </span>
        </div>
      ))}
    </div>
  );
}

// ZB-034: real retention (5–15%) rendered as one flat pale green under a fixed 0–100% ramp.
// Normalise the ramp to the observed max of the non-k0 (retention) cells instead, so the
// actual spread of the data uses the full colour range. Ramp uses the darker --good tone
// (#0a6f4d) so the top of the scale can still reach a white-text-safe contrast.
const RAMP_RGB = "10 111 77"; // matches --good
// Contrast crossover (computed against solid RAMP_RGB mixed toward white): ink (#16161d) stays
// ≥4.5:1 up to ratio≈0.81, white only clears 4.5:1 from ratio≈0.88 — switch at the empirical
// midpoint (0.85) where whichever text color is used gets the least-bad result.
const WHITE_TEXT_RATIO = 0.85;

export function CohortGrid({ cohorts }: { cohorts: { first_month: string; k: number; active: number; cohort_size: number }[] }) {
  const months = [...new Set(cohorts.map((c) => c.first_month))].sort();
  const maxK = Math.max(...cohorts.map((c) => c.k), 0);
  const cell = new Map(cohorts.map((c) => [`${c.first_month}|${c.k}`, c]));
  const monthFa = (iso: string) =>
    new Intl.DateTimeFormat("fa-IR", { month: "short", year: "2-digit" }).format(new Date(iso.slice(0, 10) + "T12:00:00"));
  const retentionShares = cohorts.filter((c) => c.k > 0 && c.cohort_size > 0).map((c) => c.active / c.cohort_size);
  const maxShare = retentionShares.length ? Math.max(...retentionShares) : 0;
  return (
    <div className="tbl-wrap">
      <div className="cohort" style={{ gridTemplateColumns: `90px repeat(${maxK + 1}, minmax(44px, 1fr))` }}>
        <div />
        {Array.from({ length: maxK + 1 }, (_, k) => (
          <div key={k} style={{ textAlign: "center", color: "var(--ink-3)" }}>{k === 0 ? "ماه ورود" : `+${k}`}</div>
        ))}
        {months.map((m0) => (
          <FragmentRow key={m0} m0={m0} maxK={maxK} cell={cell} monthFa={monthFa} maxShare={maxShare} />
        ))}
      </div>
      <div className="cohort-legend">
        <span>کم</span>
        <span className="ramp" aria-hidden>
          {[0.15, 0.4, 0.65, 0.9].map((a) => <span key={a} style={{ background: `rgb(${RAMP_RGB} / ${a})` }} />)}
        </span>
        <span>زیاد (تا {pct(maxShare, 0)})</span>
      </div>
      <p style={{ fontSize: "var(--fs-xs)", color: "var(--ink-3)", marginTop: 6 }}>
        هر خانه: سهم مشتریانِ آن ماهِ ورود که در ماه‌های بعد دوباره خرید موفق داشتند. رنگ‌ها نسبت به
        بیشترین بازگشتِ مشاهده‌شده در همین جدول ({pct(maxShare, 0)}) تنظیم شده‌اند، نه یک بازه ثابت ۰ تا ۱۰۰٪.
      </p>
    </div>
  );
}

function FragmentRow({ m0, maxK, cell, monthFa, maxShare }: {
  m0: string; maxK: number;
  cell: Map<string, { active: number; cohort_size: number }>;
  monthFa: (s: string) => string;
  maxShare: number;
}) {
  return (
    <>
      <div style={{ direction: "rtl", textAlign: "start", fontWeight: 600, alignSelf: "center" }}>{monthFa(m0)}</div>
      {Array.from({ length: maxK + 1 }, (_, k) => {
        const c = cell.get(`${m0}|${k}`);
        if (!c) return <div key={k} className="cell" style={{ background: "transparent" }} />;
        const share = c.cohort_size ? c.active / c.cohort_size : 0;
        const ratio = k > 0 && maxShare > 0 ? Math.min(share / maxShare, 1) : 0;
        const alpha = Math.min(0.1 + ratio * 0.85, 0.95);
        return (
          <div key={k} className="cell num"
               title={`${faNum(c.active)} از ${faNum(c.cohort_size)}`}
               style={{
                 background: k === 0 ? "var(--surface-2)" : `rgb(${RAMP_RGB} / ${alpha})`,
                 color: k > 0 && ratio > WHITE_TEXT_RATIO ? "#fff" : "var(--ink)",
               }}>
            {k === 0 ? faNum(c.cohort_size) : pct(share, 0)}
          </div>
        );
      })}
    </>
  );
}
