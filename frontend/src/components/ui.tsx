import type { Evidence } from "../api";
import { useApp } from "../ctx";

/* one coherent inline icon set: 1.8 stroke, round caps */
const I = (d: string) => (p: { className?: string }) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden className={p.className}>
    <path d={d} />
  </svg>
);
export const IconHome = I("M3 11l9-8 9 8M5 9v11h5v-6h4v6h5V9");
export const IconFunnel = I("M3 4h18l-7 8v7l-4-2v-5L3 4z");
export const IconUsers = I("M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM22 21v-2a4 4 0 0 0-3-3.87M15 3.13a4 4 0 0 1 0 7.75");
export const IconScale = I("M12 3v18M5 7l7-4 7 4M3 13l2-6 2 6a3 3 0 0 1-4 0zM17 13l2-6 2 6a3 3 0 0 1-4 0z");
export const IconMore = I("M5 12h.01M12 12h.01M19 12h.01");
export const IconSearch = I("M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.3-4.3");
export const IconClose = I("M18 6L6 18M6 6l12 12");
export const IconDelta = I("M3 20h18L12 4 3 20z");
export const IconChat = I("M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v10z");
export const IconShield = I("M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z");
export const IconMic = I("M12 2a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3zM5 10v1a7 7 0 0 0 14 0v-1M12 18v4");
export const IconGauge = I("M12 14l4-4M4 20a8 8 0 1 1 16 0M12 14a2 2 0 1 0 0-.01");
export const IconServer = I("M4 5h16v5H4zM4 14h16v5H4zM8 7.5h.01M8 16.5h.01");
export const IconSpark = I("M12 3v6m0 6v6M3 12h6m6 0h6M6 6l3 3m6 6l3 3M18 6l-3 3M9 15l-3 3");
export const IconPlug = I("M9 2v6M15 2v6M7 8h10v3a5 5 0 0 1-10 0zM12 16v6");

/** ZarinPal-style brand mark: a skewed yellow bar + a blue dot. */
export function ZMark({ size = 34 }: { size?: number }) {
  const s = size / 56;
  return (
    <div className="zmark" style={{ width: size, height: size }} aria-hidden>
      <div className="z-bar" style={{ insetInlineEnd: 12 * s, top: 6 * s, width: 26 * s, height: 44 * s, borderRadius: 8 * s }} />
      <div className="z-dot" style={{ insetInlineEnd: 28 * s, top: 10 * s, width: 26 * s, height: 26 * s }} />
    </div>
  );
}

export function Section(p: { title: React.ReactNode; sub?: string; children: React.ReactNode }) {
  return (
    <section className="section">
      <h2>{p.title}</h2>
      {p.sub && <p className="sub">{p.sub}</p>}
      {p.children}
    </section>
  );
}

/** the signature affordance: «این عدد از کجا آمد؟». When no visible label text is given
 *  (icon-only KPI strips), falls back to a real ≥24×24 icon hit area instead of an empty,
 *  zero-size button — the aria-label always carries the accessible name either way. */
export function EvBtn(p: { title: string; items: Evidence[]; sampleOutcome?: string; label?: string }) {
  const { openEvidence } = useApp();
  return (
    <button type="button" className="ev-btn" onClick={() => openEvidence(p.title, p.items, p.sampleOutcome)}
            aria-label={`نحوه محاسبه ${p.title}`}>
      {p.label || <IconSearch />}
    </button>
  );
}

export function ConfChip({ level }: { level: "high" | "medium" | "low" }) {
  const map = { high: ["chip-good", "اطمینان بالا"], medium: ["chip-warn", "اطمینان متوسط"], low: ["chip-mute", "اطمینان پایین"] } as const;
  const [cls, label] = map[level];
  return <span className={`chip ${cls}`}>{label}</span>;
}

export function Empty(p: { title: string; body: string }) {
  return (
    <div className="empty" role="status">
      <b>{p.title}</b>
      {p.body}
    </div>
  );
}

export function Skeleton({ h = 120 }: { h?: number }) {
  return <div className="skel" style={{ height: h }} aria-hidden />;
}

export function Loading({ rows = 3 }: { rows?: number }) {
  return (
    <div style={{ display: "grid", gap: 14 }} aria-busy="true" aria-label="در حال بارگذاری">
      {Array.from({ length: rows }, (_, i) => <Skeleton key={i} h={i === 0 ? 90 : 150} />)}
    </div>
  );
}
