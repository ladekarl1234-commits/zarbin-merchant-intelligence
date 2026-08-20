import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";

/** Plain-language explanation for a technical term: یعنی چه؟ / چرا مهم است؟ / چطور تفسیر کنم؟ */
export type Tip = { title: string; what: string; why: string; how: string };

export const TIPS: Record<string, Tip> = {
  gmv: { title: "فروش موفق", what: "جمع مبلغ همه پرداخت‌هایی که کامل و تایید شدند.", why: "این پولی است که واقعاً وارد حساب شما شده — معیار اصلی سلامت فروش.", how: "روند آن را دنبال کنید؛ افت ناگهانی یعنی جایی از مسیر پرداخت مشکل دارد." },
  conv: { title: "نرخ تکمیل پرداخت", what: "از هر ۱۰۰ مشتری که به صفحه پرداخت رسیدند، چند نفر پرداختشان کامل شد.", why: "مشتری‌ای که تا پرداخت آمده، سخت‌ترین بخش راه را رفته؛ از دست دادنش گران است.", how: "با همتایان مقایسه کنید تا بدانید طبیعی است یا نه." },
  median: { title: "میانه مبلغ تراکنش", what: "مبلغی که نیمی از خریدها بالاتر و نیمی پایین‌تر از آن هستند.", why: "از «میانگین» واقعی‌تر است چون چند خرید خیلی بزرگ آن را منحرف نمی‌کند.", how: "اگر میانه پایین آمده، مشتریان به سمت خریدهای ارزان‌تر رفته‌اند." },
  customers: { title: "مشتریان پرداخت‌کننده", what: "تعداد کارت‌های بانکی یکتایی که در این دوره خرید موفق داشتند.", why: "رشد فروش سالم یعنی رشد مشتری، نه فقط خرید بیشترِ همان چند نفر.", how: "کنار «سهم مشتریان تکراری» بخوانید تا ترکیب جدید/قدیمی را ببینید." },
  verify: { title: "تایید نهایی (Verify)", what: "مرحله‌ای که فروشگاه شما پس از پرداخت مشتری، دریافت پول را به زرین‌پال اعلام می‌کند.", why: "بدون این تایید، پولِ تسویه‌شده به‌طور کامل به چرخه مالی شما نمی‌نشیند.", how: "اگر پرداخت تاییدنشده دارید، اول اتصال فنی (callback) فروشگاه را بررسی کنید." },
  conf: { title: "سطح اطمینان", what: "چقدر شواهد پشت این نتیجه محکم است — بر اساس حجم نمونه و کیفیت مقایسه.", why: "عدد بدون اطمینان می‌تواند گمراه‌کننده باشد؛ ما به جای پنهان‌کردن، صادقانه برچسب می‌زنیم.", how: "«اطمینان بالا» یعنی با خیال راحت اقدام کنید؛ «متوسط» یعنی اول کم‌هزینه آزمایش کنید." },
  peers: { title: "همتایان", what: "کسب‌وکارهایی با صنف، اندازه فروش و مبلغ تراکنش مشابه شما.", why: "مقایسه با میانگین کل بازار بی‌معنی است — یک سوپرمارکت را نباید با طلافروشی سنجید.", how: "حداقل ۵ همتای واقعی لازم است؛ اگر نبود، زرین‌بین اصلاً مقایسه نشان نمی‌دهد." },
  recovery: { title: "بازیابی با تلاش دوباره", what: "پرداخت‌هایی که بار اول شکست خوردند اما مشتری دوباره تلاش کرد و موفق شد.", why: "نشان می‌دهد چقدر از شکست‌ها قابل نجات‌اند — با یک پیام یا دکمه «تلاش مجدد».", how: "نرخ بالا خوب است؛ اما بهتر از آن، کم‌کردن شکستِ بار اول است." },
  noattempt: { title: "انصراف پیش از پرداخت", what: "مشتری صفحه پرداخت را باز کرد اما هرگز دکمه پرداخت را نزد.", why: "این مشکل درگاه یا بانک نیست — مشکل قبل از پرداخت است: اعتماد، هزینه ارسال، فرم طولانی.", how: "اگر از همتایان بالاتر است، مسیر قبل از درگاه را ساده و شفاف کنید." },
  inbank: { title: "رهاشدن در بانک", what: "مشتری به صفحه بانک رسید اما پرداخت را کامل نکرد.", why: "معمولاً یعنی خطای رمز دوم، کندی صفحه بانک یا انصراف لحظه آخر.", how: "سهم بالا را با پشتیبانی زرین‌پال مطرح کنید؛ شاید درگاه جایگزین بهتر باشد." },
  psp: { title: "درگاه بانکی (PSP)", what: "شرکتی که تراکنش کارت را به شبکه بانکی می‌رساند؛ زرین‌پال بین چند درگاه توزیع می‌کند.", why: "نرخ موفقیت درگاه‌ها متفاوت است و مستقیم روی فروش شما اثر دارد.", how: "انتخاب درگاه دست شما نیست، اما شکاف بزرگ را می‌توانید با پشتیبانی مطرح کنید." },
  cohort: { title: "تحلیل بازگشت (کوهورت)", what: "مشتریان بر اساس ماهِ اولین خریدشان گروه می‌شوند؛ بعد می‌بینیم هر گروه در ماه‌های بعد چقدر برگشت.", why: "تنها راه فهمیدن اینکه مشتری جدید «می‌ماند» یا فقط یک‌بار می‌خرد.", how: "ستون +۱ مهم‌ترین است: چند درصد ماه بعد برگشتند؟" },
  sessions: { title: "جلسه پرداخت", what: "هر بار که برای مشتری صفحه پرداخت ساخته می‌شود، یک «جلسه» است — حتی با چند تلاش.", why: "شمارش تلاش‌ها به جای جلسه‌ها، آمار را دوبرابر باد می‌کند.", how: "همه نرخ‌های زرین‌بین بر پایه جلسه است؛ هر جلسه فقط یک بار." },
  decomp: { title: "تجزیه دقیق تغییر", what: "تغییر فروش ریاضی‌وار به سه سهم تفکیک می‌شود: تعداد مشتری، نرخ تکمیل، مبلغ متوسط.", why: "به جای حدس («شاید تبلیغات بود؟»)، دقیقاً می‌دانید کدام اهرم حرکت کرده.", how: "جمع سه سهم دقیقاً برابر کل تغییر است؛ بزرگ‌ترین سهم، جای تمرکز شماست." },
  ticket: { title: "مبلغ متوسط", what: "میانگین مبلغ هر خرید موفق در دوره.", why: "فروش = مشتری × نرخ تکمیل × همین عدد؛ یکی از سه اهرم اصلی رشد.", how: "افت آن همراه رشد مشتری طبیعی است (خریداران جدید محتاط‌ترند)." },
  deterministic: { title: "محاسبه قطعی", what: "این پاسخ با کوئری مستقیم روی داده پرداخت شما ساخته شده، نه با حدسِ مدل زبانی.", why: "یعنی عدد قابل دفاع است: همان کوئری، همیشه همان جواب.", how: "با «این عدد از کجا آمد؟» می‌توانید تعریف، فرمول و کوئری را ببینید." },
  verified: { title: "موفق (Verified)", what: "پرداخت کامل شد و فروشگاه هم آن را تایید کرد.", why: "تنها وضعیتی که قطعاً پول شماست.", how: "مبنای همه اعداد «فروش موفق»." },
  paid: { title: "تسویه بدون تایید", what: "بانک پول را کشیده اما فروشگاه شما تایید نکرده.", why: "پول واقعی است که بلاتکلیف مانده.", how: "از پنل زرین‌پال قابل پیگیری و تایید است." },
  failedbank: { title: "خطای صریح بانکی", what: "بانک تراکنش را با کد خطا رد کرد (موجودی، رمز، سقف...).", why: "تنها دسته‌ای که واقعاً «خطای پرداخت» است.", how: "کدهای پرتکرار را در صفحه مسیر پرداخت ببینید." },
  reversed: { title: "برگشت‌خورده", what: "مبلغ کسر شد اما به دلیل نقص فرایند به مشتری برگشت.", why: "برای مشتری آزاردهنده است و اعتماد را می‌سوزاند.", how: "سهم بالای آن را حتماً با پشتیبانی مطرح کنید." },
  p95: { title: "زمان پاسخ ۹۵٪ درخواست‌ها", what: "۹۵ درصد درخواست‌ها سریع‌تر از این زمان پاسخ گرفته‌اند.", why: "میانگین، کندی‌های واقعی را پنهان می‌کند؛ p95 تجربه بدترین‌ها را نشان می‌دهد.", how: "اگر بالا رفت، دنبال یک endpoint یا کوئری کند بگردید." },
};

function pos(el: HTMLElement) {
  const r = el.getBoundingClientRect();
  const top = Math.min(window.innerHeight - 230, r.bottom + 10);
  const right = Math.max(12, Math.min(window.innerWidth - 320, window.innerWidth - r.right - 150 + r.width / 2));
  return { top, right };
}

/** A term with a progressive-disclosure tooltip. Opens on hover, keyboard focus, and tap.
 *  `tip` can be a TIPS key or Tip object (rich 3-part), or any other string (a simple one-liner). */
export function Term({ label, tip }: { label: React.ReactNode; tip: Tip | string }) {
  const rich: Tip | undefined = typeof tip === "string" ? TIPS[tip] : tip;
  const simple = typeof tip === "string" && !rich ? tip : null;
  const [box, setBox] = useState<{ top: number; right: number } | null>(null);
  const ref = useRef<HTMLSpanElement>(null);
  const popId = useId();
  const open = () => ref.current && setBox(pos(ref.current));
  const close = () => setBox(null);
  useEffect(() => {
    if (!box) return;
    const on = () => close();
    window.addEventListener("scroll", on, true);
    window.addEventListener("resize", on);
    return () => { window.removeEventListener("scroll", on, true); window.removeEventListener("resize", on); };
  }, [box]);
  if (!rich && !simple) return <>{label}</>;
  return (
    <span className="term">
      <span ref={ref} className="lbl" tabIndex={0} role="button" aria-label={`توضیح: ${rich?.title ?? "بیشتر"}`}
            aria-describedby={box ? popId : undefined}
            onMouseEnter={open} onMouseLeave={close} onFocus={open} onBlur={close}
            onClick={() => (box ? close() : open())}
            onKeyDown={(e) => { if (e.key === "Escape") close(); }}>{label}</span>
      {box && createPortal(
        <div id={popId} className="tip-pop" role="tooltip" style={{ top: box.top, insetInlineEnd: box.right }}>
          {rich ? (
            <>
              <div className="tt">{rich.title}</div>
              <div className="tl">
                <div><span className="tk">یعنی چه؟</span> {rich.what}</div>
                <div><span className="tk">چرا مهم است؟</span> {rich.why}</div>
                <div><span className="tk">چطور تفسیر کنم؟</span> {rich.how}</div>
              </div>
            </>
          ) : <div className="tl">{simple}</div>}
        </div>, document.body)}
    </span>
  );
}
