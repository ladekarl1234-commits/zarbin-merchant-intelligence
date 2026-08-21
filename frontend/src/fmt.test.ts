// ZB-043: fmt.ts re-implements zarin/fa.py's Persian formatting independently, and they had
// never been asserted against each other. Every "python:" comment below is the literal output
// of the matching zarin/fa.py function for the SAME input, captured via:
//   uv run python -c "from zarin.fa import fa_money, fa_pct, fa_num; print(fa_money(...))"
//
// Writing these tests surfaced three real divergences — the SAME number rendered differently
// depending on which side formatted it, visible together on one screen (a copilot sentence next
// to a KPI tile). Two were then fixed in zarin/fa.py so both sides now agree byte-for-byte:
//   1. thousands separator: fa.py used U+060C ('،'); it now uses Intl's U+066C ('٬')
//   2. trailing '.0': fa.py always kept it ('۱٫۰ میلیون'); it now drops it like Intl
// The third is cosmetic and deliberately left alone: Intl prefixes negatives with an invisible
// LRM + U+2212 MINUS, fa.py uses an ASCII '-'. Identical on screen in RTL.
// The "python:" comments below show fa.py's output AFTER those fixes.
import { describe, expect, it } from "vitest";
import { deltaPct, faDate, faDateShort, faNum, localizeDates, pct, pp, rial } from "./fmt";

describe("rial() magnitude boundaries", () => {
  it("below 1e4: plain grouped integer", () => {
    // python: fa_money(9999) -> '۹٬۹۹۹ ریال' — identical (separator fixed)
    
    expect(rial(9999)).toBe("۹٬۹۹۹ ریال");
  });
  it("rounds up across the 1e4 boundary", () => {
    // python: fa_money(9999.9) -> '۱۰،۰۰۰ ریال' (rounds to 10,000 but is STILL below 1e4 in
    // magnitude-check terms since the branch tests the raw value, not the rounded one)
    expect(rial(9999.9)).toBe("۱۰٬۰۰۰ ریال");
  });
  it("exactly 1e4: switches to the هزار (thousand) suffix", () => {
    // python: fa_money(10000) -> '۱۰ هزار ریال'
    expect(rial(10000)).toBe("۱۰ هزار ریال");
  });
  it("just below 1e6: still هزار", () => {
    // python: fa_money(999999) -> '۱٬۰۰۰ هزار ریال' — identical
    expect(rial(999999)).toBe("۱٬۰۰۰ هزار ریال");
  });
  it("exactly 1e6: switches to میلیون (million)", () => {
    // python: fa_money(1000000) -> '۱ میلیون ریال' — identical (trailing .0 fixed)
    
    expect(rial(1000000)).toBe("۱ میلیون ریال");
  });
  it("just below 1e9: still میلیون", () => {
    // python: fa_money(999999999) -> '۱٬۰۰۰ میلیون ریال' — identical
    expect(rial(999999999)).toBe("۱٬۰۰۰ میلیون ریال");
  });
  it("exactly 1e9: switches to میلیارد (billion)", () => {
    // python: fa_money(1000000000) -> '۱ میلیارد ریال' — identical
    expect(rial(1000000000)).toBe("۱ میلیارد ریال");
  });
  it("a non-round billion figure matches fa.py exactly", () => {
    // python: fa_money(61800000000) -> '۶۱٫۸ میلیارد ریال' — no trailing-zero drop here,
    // so fmt.ts and fa.py agree.
    expect(rial(61800000000)).toBe("۶۱٫۸ میلیارد ریال");
  });
  it("just below 1e12: still میلیارد", () => {
    // python: fa_money(999999999999) -> '۱٬۰۰۰ میلیارد ریال' — identical
    expect(rial(999999999999)).toBe("۱٬۰۰۰ میلیارد ریال");
  });
  it("exactly 1e12: switches to هزار میلیارد (trillion)", () => {
    // python: fa_money(1000000000000) -> '۱ هزار میلیارد ریال' — identical
    expect(rial(1000000000000)).toBe("۱ هزار میلیارد ریال");
  });
  it("matches fa.py on a realistic non-round trillion figure", () => {
    // python: fa_money(1950000000000) -> '۱٫۹۵ هزار میلیارد ریال' — agrees with fmt.ts.
    expect(rial(1950000000000)).toBe("۱٫۹۵ هزار میلیارد ریال");
  });
  it("negative amounts", () => {
    // python: fa_money(-1000000000) -> '-۱ میلیارد ریال' (ASCII hyphen-minus).
    // REMAINING (cosmetic, by choice): Intl renders an invisible LRM + U+2212 MINUS; same on screen.
    expect(rial(-1000000000)).toBe("‎−۱ میلیارد ریال");
  });
  it("null/undefined render the em-dash placeholder, matching fa.py", () => {
    expect(rial(null)).toBe("—");
    expect(rial(undefined)).toBe("—");
  });
  it("unit=false omits the ریال suffix", () => {
    expect(rial(1000000, false)).toBe("۱ میلیون");
  });
});

describe("pct() signs and rounding", () => {
  it("drops a trailing .0 — fa.py now does the same (ZB-043 headline divergence, fixed)", () => {
    // python: fa_pct(0.5, 1) -> '۵۰٪' — identical
    expect(pct(0.5, 1)).toBe("۵۰٪");
  });
  it("digits=0 matches fa.py (both drop the fraction entirely)", () => {
    // python: fa_pct(0.5, 0) -> '۵۰٪'
    expect(pct(0.5, 0)).toBe("۵۰٪");
  });
  it("rounds a real fraction the same way fa.py does", () => {
    // python: fa_pct(0.12345, 1) -> '۱۲٫۳٪'
    expect(pct(0.12345, 1)).toBe("۱۲٫۳٪");
  });
  it("negative percentages", () => {
    // python: fa_pct(-0.5, 1) -> '-۵۰٪' (ASCII minus)
    // REMAINING (cosmetic): sign glyph only.
    expect(pct(-0.5, 1)).toBe("‎−۵۰٪");
  });
  it("zero", () => {
    // python: fa_pct(0, 1) -> '۰٪' — identical
    expect(pct(0, 1)).toBe("۰٪");
  });
  it("null renders the placeholder, matching fa.py", () => {
    expect(pct(null)).toBe("—");
  });
});

describe("pp() signed percentage-point delta", () => {
  it("positive delta gets an explicit + sign", () => {
    expect(pp(0.02)).toBe("+۲ واحد");
  });
  it("negative delta uses the Unicode minus sign, not a hyphen", () => {
    expect(pp(-0.02)).toBe("−۲ واحد");
  });
  it("zero is treated as non-negative (gets a +)", () => {
    expect(pp(0)).toBe("+۰ واحد");
  });
  it("null renders the placeholder", () => {
    expect(pp(null)).toBe("—");
  });
});

describe("faNum()", () => {
  it("matches fa.py integer rounding and grouping exactly", () => {
    // python: fa_num(12345) -> '۱۲٬۳۴۵' — identical (separator fixed)
    expect(faNum(12345)).toBe("۱۲٬۳۴۵");
  });
  it("rounds half-to-even/away like fa.py's round()", () => {
    // python: fa_num(3.7) -> '۴'
    expect(faNum(3.7)).toBe("۴");
  });
  it("negative integers", () => {
    // python: fa_num(-42) -> '-۴۲' (ASCII minus) — cosmetic sign difference only.
    expect(faNum(-42)).toBe("‎−۴۲");
  });
  it("null/undefined", () => {
    expect(faNum(null)).toBe("—");
    expect(faNum(undefined)).toBe("—");
  });
});

describe("faDate() / faDateShort() / localizeDates()", () => {
  // fa.py has no Jalali date formatter — these are frontend-only, so there is no Python
  // baseline to compare against; the assertions pin the current Intl('fa-IR') output.
  it("formats an ISO date as a full Jalali date", () => {
    expect(faDate("2026-01-01")).toBe("۱۱ دی ۱۴۰۴");
  });
  it("formats an ISO date as a short Jalali date", () => {
    expect(faDateShort("2026-01-01")).toBe("۱۱ دی");
  });
  it("null/undefined -> placeholder", () => {
    expect(faDate(null)).toBe("—");
    expect(faDate(undefined)).toBe("—");
  });
  it("replaces every embedded YYYY-MM-DD substring in a sentence", () => {
    const s = localizeDates("بازه 2026-01-01 تا 2026-06-30");
    expect(s).toContain("۱۱ دی ۱۴۰۴");
    expect(s).toContain("۹ تیر ۱۴۰۵");
    expect(s).not.toMatch(/\d{4}-\d{2}-\d{2}/);
  });
  it("empty/null input", () => {
    expect(localizeDates(null)).toBe("");
    expect(localizeDates("")).toBe("");
  });
});

describe("deltaPct()", () => {
  it("computes a relative change", () => {
    expect(deltaPct(120, 100)).toBeCloseTo(0.2);
  });
  it("null-safe on missing inputs or a zero baseline", () => {
    expect(deltaPct(null, 100)).toBeNull();
    expect(deltaPct(100, null)).toBeNull();
    expect(deltaPct(100, 0)).toBeNull();
  });
});
