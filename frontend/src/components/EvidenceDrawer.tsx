import { useEffect, useRef, useState } from "react";
import type { SessionSample } from "../api";
import { get } from "../api";
import { useApp } from "../ctx";
import { faDate, faNum, localizeDates, rial } from "../fmt";
import { IconClose } from "./ui";

const OUTCOME_FA: Record<string, string> = {
  verified: "موفق", paid_unverified: "تاییدنشده", no_attempt: "بدون اقدام",
  abandoned_inbank: "رها در بانک", failed_bank: "خطای بانکی", reversed: "برگشت‌خورده",
};

export default function EvidenceDrawer() {
  const { drawer, closeEvidence, merchant, period } = useApp();
  const [samples, setSamples] = useState<SessionSample | null>(null);
  const [sampleErr, setSampleErr] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // close the drawer if the merchant or period changes underneath it, so its
  // evidence can never describe a selection the user has since navigated away from
  useEffect(() => {
    if (drawer) closeEvidence();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [merchant, period.f, period.t]);

  useEffect(() => {
    setSamples(null);
    setSampleErr(false);
    if (!drawer) return;
    const opener = document.activeElement as HTMLElement | null;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeEvidence();
      if (e.key === "Tab" && ref.current) {
        const items = ref.current.querySelectorAll<HTMLElement>(
          'button, [href], input, [tabindex]:not([tabindex="-1"])');
        if (!items.length) return;
        const first = items[0], last = items[items.length - 1];
        const active = document.activeElement as Node | null;
        // if focus is outside the drawer (e.g. on the tabIndex=-1 container after open),
        // pull it back in rather than letting Tab escape to the page behind the backdrop
        if (!active || !ref.current.contains(active)) {
          e.preventDefault();
          (e.shiftKey ? last : first).focus();
        } else if (e.shiftKey && active === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && active === last) { e.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";  // scroll lock
    ref.current?.focus();
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
      opener?.focus();  // restore focus to the element that opened the drawer
    };
  }, [drawer, closeEvidence]);

  if (!drawer) return null;

  const loadSamples = () =>
    get<SessionSample>("evidence/sessions", {
      m: merchant, f: period.f, t: period.t, outcome: drawer.sampleOutcome,
    }).then((s) => { setSamples(s); setSampleErr(false); })
      .catch(() => setSampleErr(true));

  return (
    <>
      <div className="backdrop" onClick={closeEvidence} aria-hidden />
      <div className="drawer" role="dialog" aria-modal="true" aria-label={`نحوه محاسبه: ${drawer.title}`}
           tabIndex={-1} ref={ref}>
        <div className="drawer-head">
          <h2>این عدد از کجا آمد؟ — {drawer.title}</h2>
          <button className="btn" onClick={closeEvidence} aria-label="بستن" style={{ padding: "5px 8px" }}>
            <IconClose className="" />
          </button>
        </div>
        <div className="drawer-body">
          {drawer.items.map((ev, i) => ev.sql !== "" && (
            <div key={i} style={{ marginBottom: i < drawer.items.length - 1 ? 26 : 0 }}>
              <h3>متریک</h3>
              <p style={{ fontWeight: 700 }}>{ev.name_fa}</p>
              <p style={{ fontSize: "var(--fs-s)", color: "var(--ink-2)" }}>{ev.definition_fa}</p>
              <h3>فرمول</h3>
              <p className="num" style={{ fontSize: "var(--fs-s)", direction: "ltr", textAlign: "left", fontFamily: "Consolas, monospace" }}>{ev.formula}</p>
              <h3>مشخصات محاسبه</h3>
              <dl className="kv">
                {ev.period && <><dt>دوره</dt><dd className="num">{localizeDates(ev.period)}</dd></>}
                <dt>سطح داده</dt><dd>{ev.grain === "session" ? "جلسه پرداخت" : ev.grain === "customer" ? "مشتری (کارت)" : ev.grain}</dd>
                {ev.n != null && <><dt>حجم نمونه</dt><dd className="num">{faNum(ev.n)}</dd></>}
                <dt>زمان محاسبه</dt><dd className="num" style={{ direction: "ltr", textAlign: "start" }}>{ev.computed_at}</dd>
              </dl>
              {Object.keys(ev.params).length > 0 && (
                <>
                  <h3>پارامترها</h3>
                  <dl className="kv">
                    {Object.entries(ev.params).map(([k, v]) => (
                      <span key={k} style={{ display: "contents" }}>
                        <dt className="num" style={{ direction: "ltr", textAlign: "start" }}>{k}</dt>
                        <dd className="num">{String(v)}</dd>
                      </span>
                    ))}
                  </dl>
                </>
              )}
              <h3>{ev.sql_kind === "method" ? "روش محاسبه" : "کوئری اجراشده"}</h3>
              <pre className="sqlbox">{ev.sql}</pre>
              {(ev.note_fa || ev.method_fa || ev.rule_fa) && (
                <div className="callout callout-info">{ev.note_fa ?? ev.method_fa ?? ev.rule_fa}</div>
              )}
              {ev.caveats.map((c, j) => <div className="callout" key={j}>{c}</div>)}
            </div>
          ))}

          {drawer.sampleOutcome && (<>
          <h3 style={{ marginTop: 24 }}>ردیابی تا جلسه‌های منبع</h3>
          {sampleErr ? (
            <div className="callout">دریافت نمونه‌ها ممکن نشد. <button className="ev-btn" onClick={loadSamples}>تلاش دوباره</button></div>
          ) : !samples ? (
            <button className="btn" onClick={loadSamples}>نمایش نمونه جلسه‌های منبع</button>
          ) : (
            <>
              <p style={{ fontSize: "var(--fs-xs)", color: "var(--ink-3)", marginBottom: 8 }}>
                {samples.note_fa} (مجموع: <span className="num">{faNum(samples.total)}</span> جلسه)
              </p>
              <div className="tbl-wrap">
                <table className="tbl num">
                  <thead><tr><th>شناسه جلسه</th><th>تاریخ</th><th>مبلغ</th><th>نتیجه</th><th>تلاش‌ها</th></tr></thead>
                  <tbody>
                    {samples.rows.map((r) => (
                      <tr key={r.session_key}>
                        <td>{r.session_key}</td>
                        <td>{faDate(r.d)}</td>
                        <td>{rial(r.amount, false)}</td>
                        <td>{OUTCOME_FA[r.outcome] ?? r.outcome}</td>
                        <td>{faNum(r.n_tries)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
          </>)}
        </div>
      </div>
    </>
  );
}
