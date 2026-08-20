import { useRef, useState } from "react";
import { ZMark } from "../components/ui";

/** Demo sign-in gate matching the redesign: phone → OTP → app. There is no auth backend in the
 *  challenge build, so this is a client-side front door (any 5-digit code proceeds). */
export default function Login({ onLogin }: { onLogin: () => void }) {
  const [step, setStep] = useState<"phone" | "otp">("phone");
  const [phone, setPhone] = useState("");
  const [otp, setOtp] = useState(["", "", "", "", ""]);
  const boxes = useRef<(HTMLInputElement | null)[]>([]);

  const setDigit = (i: number, v: string) => {
    const d = v.replace(/\D/g, "").slice(-1);
    setOtp((o) => o.map((x, j) => (j === i ? d : x)));
    if (d && i < 4) boxes.current[i + 1]?.focus();
  };
  const phoneShown = phone.trim() || "0912 345 6789";

  return (
    <div className="login-wrap" dir="rtl">
      <div className="login-card-wrap">
        <div className="login-card">
          <div className="login-head">
            <ZMark size={56} />
            <div>
              <div className="login-title">زرین‌بین</div>
              <div className="login-sub">هوش کسب‌وکار پذیرندگان زرین‌پال</div>
            </div>
          </div>

          {step === "phone" ? (
            <form onSubmit={(e) => { e.preventDefault(); setStep("otp"); setOtp(["", "", "", "", ""]); setTimeout(() => boxes.current[0]?.focus(), 0); }}>
              <label className="field-label" htmlFor="phone">شماره موبایل</label>
              <input id="phone" dir="ltr" className="field num" value={phone} onChange={(e) => setPhone(e.target.value)}
                     placeholder="0912 000 0000" inputMode="tel" style={{ textAlign: "left", letterSpacing: "0.06em" }} />
              <button className="btn btn-brand btn-block" type="submit" style={{ marginTop: 14 }}>دریافت کد ورود</button>
              <p className="login-note">با حساب زرین‌پال خود وارد شوید؛ نیازی به ثبت‌نام جداگانه نیست.</p>
            </form>
          ) : (
            <form onSubmit={(e) => { e.preventDefault(); onLogin(); }}>
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
              <button className="btn btn-brand btn-block" type="submit" style={{ marginTop: 18 }}>ورود</button>
              <div style={{ display: "flex", justifyContent: "space-between", marginTop: 12, fontSize: "0.78rem" }}>
                <button type="button" className="linklike" style={{ color: "var(--ink-3)" }} onClick={() => setStep("phone")}>تغییر شماره</button>
                <button type="button" className="linklike">ارسال دوباره کد</button>
              </div>
            </form>
          )}

          <div className="login-roles">
            <p style={{ margin: "0 0 10px", fontSize: "0.75rem", color: "var(--ink-3)", textAlign: "center" }}>
              بسته به نقش حساب شما، پس از ورود به فضای مناسب هدایت می‌شوید:
            </p>
            <div className="role-pills">
              <span className="role-pill"><span className="dot" style={{ background: "var(--brand)" }} />فضای پذیرنده</span>
              <span className="role-pill"><span className="dot" style={{ background: "var(--blue-2)" }} />مرکز کنترل عملیات</span>
            </div>
          </div>
        </div>
        <p className="login-foot">زرین‌بین · محصولی در اکوسیستم زرین‌پال</p>
      </div>
    </div>
  );
}
