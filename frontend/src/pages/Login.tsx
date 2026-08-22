import { useRef, useState } from "react";
import { get } from "../api";
import { IconHome, IconServer, ZMark } from "../components/ui";

type WS = "merchant" | "ops";
const META: Record<WS, { title: string; sub: string }> = {
  merchant: { title: "فضای پذیرنده / مشتری", sub: "داشبورد کسب‌وکار شما — فروش، مشتری و پرداخت" },
  ops: { title: "مرکز کنترل عملیات", sub: "برای تیم‌های مدیریت، محصول، داده و عملیات" },
};

/** Two separate entry points chosen BEFORE authentication. Each path has its own login flow and,
 *  after auth, enters only its own workspace — there is no in-dashboard switching. Demo gate: no
 *  auth backend in the challenge build, so any 5-digit code proceeds. */
export default function Login({ onLogin }: { onLogin: (ws: WS) => void }) {
  const [step, setStep] = useState<"choose" | "phone" | "otp">("choose");
  const [target, setTarget] = useState<WS>("merchant");
  const [phone, setPhone] = useState("");
  const [otp, setOtp] = useState(["", "", "", "", ""]);
  const [submitting, setSubmitting] = useState(false);
  const boxes = useRef<(HTMLInputElement | null)[]>([]);
  const isOps = target === "ops";
  const phoneShown = phone.trim() || "0912 345 6789";

  const choose = (ws: WS) => { setTarget(ws); setStep("phone"); setPhone(""); };
  const setDigit = (i: number, v: string) => {
    const d = v.replace(/\D/g, "").slice(-1);
    setOtp((o) => o.map((x, j) => (j === i ? d : x)));
    if (d && i < 4) boxes.current[i + 1]?.focus();
  };

  return (
    <div className="login-wrap" dir="rtl">
      <div className="login-card-wrap">
        {step === "choose" ? (
          <div className="login-card">
            <div className="login-head">
              <ZMark size={56} />
              <div>
                <div className="login-title">زرین‌بین</div>
                <div className="login-sub">برای ورود، فضای کاری خود را انتخاب کنید</div>
              </div>
            </div>
            <div className="entry-list">
              <button className="entry-card" onClick={() => choose("merchant")}>
                <span className="entry-icon merchant"><IconHome /></span>
                <span className="entry-body">
                  <span className="entry-title">{META.merchant.title}</span>
                  <span className="entry-sub">{META.merchant.sub}</span>
                </span>
                <span className="entry-arrow" aria-hidden>←</span>
              </button>
              <button className="entry-card" onClick={() => choose("ops")}>
                <span className="entry-icon ops"><IconServer /></span>
                <span className="entry-body">
                  <span className="entry-title">{META.ops.title}</span>
                  <span className="entry-sub">{META.ops.sub}</span>
                </span>
                <span className="entry-arrow" aria-hidden>←</span>
              </button>
            </div>
          </div>
        ) : (
          <div className="login-card">
            <div className="login-head">
              <ZMark size={56} />
              <div>
                <div className="login-title">زرین‌بین</div>
                <div className="login-sub">
                  ورود به: <b style={{ color: isOps ? "var(--blue)" : "var(--ink)" }}>{META[target].title}</b>
                  {" · "}
                  <button type="button" className="linklike" onClick={() => setStep("choose")}>تغییر</button>
                </div>
              </div>
            </div>

            {step === "phone" ? (
              <form onSubmit={(e) => { e.preventDefault(); setStep("otp"); setOtp(["", "", "", "", ""]); setTimeout(() => boxes.current[0]?.focus(), 0); }}>
                <label className="field-label" htmlFor="phone">شماره موبایل</label>
                <input id="phone" dir="ltr" className="field num" value={phone} onChange={(e) => setPhone(e.target.value)}
                       placeholder="0912 000 0000" inputMode="tel" style={{ textAlign: "left", letterSpacing: "0.06em" }} />
                <button className={`btn btn-block ${isOps ? "btn-ink" : "btn-brand"}`} type="submit" style={{ marginTop: 14 }}>دریافت کد ورود</button>
                <p className="login-note">با حساب زرین‌پال خود وارد شوید؛ نیازی به ثبت‌نام جداگانه نیست.</p>
              </form>
            ) : (
              <form onSubmit={async (e) => {
                e.preventDefault();
                if (submitting) return;
                setSubmitting(true);
                // Auth contract with the backend: exchange the completed (demo) login for a
                // session token. This MUST be awaited before entering the workspace. The ops
                // landing page fetches /api/admin/platform on mount, and on a deployment where
                // that route requires a session the very first render answered 403 — an error
                // screen on every fresh ops login, which then "fixed itself" on the next
                // navigation and so looked like a flake rather than a race. The endpoint may
                // still be absent in an older build, so a failure is swallowed.
                try {
                  const r = await get<{ token?: string }>("auth/session", { scope: target }, "POST");
                  if (r?.token) { try { sessionStorage.setItem("zb_token", r.token); } catch { /* storage blocked */ } }
                } catch { /* older build without the endpoint */ }
                setSubmitting(false);
                onLogin(target);
              }}>
                <p style={{ margin: "0 0 14px", fontSize: "0.85rem", color: "var(--ink-2)", textAlign: "center" }}>
                  کد ۵ رقمی پیامک‌شده به <b dir="ltr" className="num">{phoneShown}</b> را وارد کنید
                </p>
                <div className="otp-row">
                  {otp.map((v, i) => (
                    <input key={i} ref={(el) => (boxes.current[i] = el)} className="otp-box num" value={v}
                           maxLength={1} inputMode="numeric" aria-label={`رقم ${i + 1}`}
                           onChange={(e) => setDigit(i, e.target.value)}
                           onKeyDown={(e) => { if (e.key === "Backspace" && !v && i > 0) boxes.current[i - 1]?.focus(); }} />
                  ))}
                </div>
                <button className={`btn btn-block ${isOps ? "btn-ink" : "btn-brand"}`} type="submit"
                        style={{ marginTop: 18 }} disabled={submitting}>{submitting ? "در حال ورود…" : "ورود"}</button>
                <div style={{ display: "flex", justifyContent: "space-between", marginTop: 12, fontSize: "0.78rem" }}>
                  <button type="button" className="linklike" style={{ color: "var(--ink-3)" }} onClick={() => setStep("phone")}>تغییر شماره</button>
                  <button type="button" className="linklike">ارسال دوباره کد</button>
                </div>
              </form>
            )}
          </div>
        )}
        <p className="login-foot">زرین‌بین · محصولی در اکوسیستم زرین‌پال</p>
      </div>
    </div>
  );
}
