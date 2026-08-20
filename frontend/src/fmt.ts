// Persian formatting: fa-IR digits, compact rial, Jalali dates via Intl.
const nf = new Intl.NumberFormat("fa-IR");
const nf1 = new Intl.NumberFormat("fa-IR", { maximumFractionDigits: 1 });
const nf2 = new Intl.NumberFormat("fa-IR", { maximumFractionDigits: 2 });

export function faNum(v: number | null | undefined): string {
  return v == null ? "—" : nf.format(Math.round(v));
}

/** Compact IRR: ۱٫۹۵ هزار میلیارد / ۶۱٫۸ میلیارد / ۴۱٫۴ میلیون ریال */
export function rial(v: number | null | undefined, unit = true): string {
  if (v == null) return "—";
  const a = Math.abs(v);
  let s: string;
  if (a >= 1e12) s = `${nf2.format(v / 1e12)} هزار میلیارد`;
  else if (a >= 1e9) s = `${nf1.format(v / 1e9)} میلیارد`;
  else if (a >= 1e6) s = `${nf1.format(v / 1e6)} میلیون`;
  else if (a >= 1e4) s = `${nf.format(Math.round(v / 1e3))} هزار`;
  else s = nf.format(Math.round(v));
  return unit ? `${s} ریال` : s;
}

export function pct(v: number | null | undefined, digits = 1): string {
  if (v == null) return "—";
  return `${new Intl.NumberFormat("fa-IR", { maximumFractionDigits: digits }).format(v * 100)}٪`;
}

/** signed pp delta */
export function pp(v: number | null | undefined): string {
  if (v == null) return "—";
  const s = nf1.format(Math.abs(v * 100));
  return `${v >= 0 ? "+" : "−"}${s} واحد`;
}

const dateFmt = new Intl.DateTimeFormat("fa-IR", { day: "numeric", month: "long", year: "numeric" });
const dateShort = new Intl.DateTimeFormat("fa-IR", { day: "numeric", month: "short" });

export function faDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return dateFmt.format(new Date(iso.slice(0, 10) + "T12:00:00"));
}

/** Replace any YYYY-MM-DD inside a string with its Jalali/Persian rendering. */
export function localizeDates(s: string | null | undefined): string {
  if (!s) return "";
  return s.replace(/\d{4}-\d{2}-\d{2}/g, (m) => faDate(m));
}
export function faDateShort(iso: string): string {
  return dateShort.format(new Date(iso.slice(0, 10) + "T12:00:00"));
}

export function deltaPct(cur: number | null, prev: number | null): number | null {
  if (cur == null || prev == null || prev === 0) return null;
  return (cur - prev) / prev;
}

export const HOURS_FA = Array.from({ length: 24 }, (_, h) => `${nf.format(h)}`);
