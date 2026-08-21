import { useEffect, useState } from "react";
import { AppProvider, useApp } from "./ctx";
import {
  IconChat, IconDelta, IconFunnel, IconGauge, IconHome, IconPlug,
  IconScale, IconServer, IconShield, IconSpark, IconUsers, ZMark,
} from "./components/ui";
import EvidenceDrawer from "./components/EvidenceDrawer";
import Login from "./pages/Login";
import Overview from "./pages/Overview";
import FunnelPage from "./pages/FunnelPage";
import CustomersPage from "./pages/CustomersPage";
import PeersPage from "./pages/PeersPage";
import ChangesPage from "./pages/ChangesPage";
import CopilotPage from "./pages/CopilotPage";
import QualityPage from "./pages/QualityPage";
import OpsOverview from "./ops/OpsOverview";
import OpsPerformance from "./ops/OpsPerformance";
import OpsAI from "./ops/OpsAI";
import OpsSources from "./ops/OpsSources";
import OpsCopilotPage from "./ops/OpsCopilotPage";

type Icon = (p: { className?: string }) => JSX.Element;
type Nav = { id?: string; label: string; short?: string; icon?: Icon; header?: boolean; el?: JSX.Element; sub?: string };
export type WS = "merchant" | "ops";

const MERCHANT: Nav[] = [
  { header: true, label: "دستیار" },
  { id: "copilot", label: "گفتگو با زرین‌بین", short: "گفتگو", icon: IconChat, el: <CopilotPage />, sub: "هوش کسب‌وکار شما — پاسخ‌ها از داده واقعی پرداخت‌ها" },
  { header: true, label: "تحلیل‌ها" },
  { id: "overview", label: "نمای کلی", short: "کلی", icon: IconHome, el: <Overview />, sub: "خلاصه اجرایی و مهم‌ترین فرصت‌های شما" },
  { id: "funnel", label: "مسیر پرداخت", short: "مسیر", icon: IconFunnel, el: <FunnelPage />, sub: "از باز شدن صفحه پرداخت تا تایید نهایی" },
  { id: "changes", label: "چه چیزی تغییر کرد؟", short: "تغییر", icon: IconDelta, el: <ChangesPage />, sub: "مقایسه نیمه اول و دوم دوره انتخابی" },
  { id: "peers", label: "مقایسه با مشابه‌ها", short: "مشابه", icon: IconScale, el: <PeersPage />, sub: "فقط با همتایان واقعی، نه میانگین بازار" },
  { id: "customers", label: "مشتریان", short: "مشتری", icon: IconUsers, el: <CustomersPage />, sub: "چه کسانی می‌خرند و آیا برمی‌گردند؟" },
  { header: true, label: "شفافیت" },
  { id: "quality", label: "کیفیت داده", short: "کیفیت", icon: IconShield, el: <QualityPage />, sub: "چه چیزی را می‌دانیم و چه چیزی را نمی‌دانیم" },
];

const OPS: Nav[] = [
  { header: true, label: "مرکز کنترل عملیات" },
  { id: "overview", label: "نمای پلتفرم", short: "پلتفرم", icon: IconServer, el: <OpsOverview />, sub: "سلامت خودِ محصول، نه یک کسب‌وکار خاص" },
  { id: "performance", label: "کارایی", short: "کارایی", icon: IconGauge, el: <OpsPerformance />, sub: "سرعت، پایداری و خطای واقعی API" },
  { id: "ai", label: "هوش مصنوعی", short: "AI", icon: IconSpark, el: <OpsAI />, sub: "کیفیت، مستندبودن و هزینه پاسخ‌ها" },
  { id: "sources", label: "منابع داده", short: "منابع", icon: IconPlug, el: <OpsSources />, sub: "دیتاست چالش یک ورودی است، نه کل سیستم" },
  { id: "copilot", label: "دستیار عملیات", short: "دستیار", icon: IconChat, el: <OpsCopilotPage />, sub: "از سلامت محصول بپرس" },
];

/** Page-only routing. Workspace is fixed by the login session (chosen before auth), never
 *  derived from the URL — so a merchant URL can never reach the operations workspace. */
function useRoute(): [string, (page: string) => void] {
  const parse = () => location.hash.match(/#\/(?:ops\/)?([\w-]+)/)?.[1] ?? "";
  const [page, setPage] = useState(parse);
  useEffect(() => {
    const on = () => { setPage(parse()); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return [page, (p) => { location.hash = `#/${p}`; }];
}

function Shell({ workspace, onLogout }: { workspace: WS; onLogout: () => void }) {
  const { meta, merchant, setMerchant, presetId, setPresetId, presets, metaError, retryMeta } = useApp();
  const ws = workspace;
  const [page, go] = useRoute();
  const [narrow, setNarrow] = useState(() => typeof window !== "undefined" && window.innerWidth < 860);
  useEffect(() => {
    const on = () => setNarrow(window.innerWidth < 860);
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);

  // ZB-022: a merchant workspace is unusable without `meta` (no merchant to fetch data for) — show
  // a retryable error instead of leaving every page stuck on an endless skeleton. Ops doesn't
  // depend on meta at all, so it's unaffected.
  if (ws === "merchant" && !meta && metaError) {
    return (
      <div style={{ minHeight: "100dvh", display: "grid", placeItems: "center", padding: 24 }}>
        <div className="empty" style={{ maxWidth: 420 }} role="alert">
          <b>خطا در بارگذاری اطلاعات اولیه</b>
          مشکلی در ارتباط با سرور پیش آمد و اطلاعات پایه بارگذاری نشد.
          <div style={{ marginTop: 12 }}>
            <button type="button" className="btn btn-brand" onClick={retryMeta}>تلاش دوباره</button>
          </div>
        </div>
      </div>
    );
  }

  const nav = ws === "ops" ? OPS : MERCHANT;
  const items = nav.filter((n) => !n.header);
  const current = items.find((n) => n.id === page) ?? items[0];
  const mkey = meta?.merchants.find((m) => m.merchant_key === merchant);

  return (
    <div className="app" data-narrow={narrow} data-workspace={ws}>
      {!narrow && (
        <aside className="sidebar">
          <div className="side-brand">
            <ZMark size={34} />
            <div>
              <div className="name">زرین‌بین</div>
              <div className="sub">{ws === "ops" ? "مرکز کنترل و عملیات" : "هوش کسب‌وکار شما"}</div>
            </div>
          </div>
          <nav className="side-nav" aria-label="بخش‌ها">
            {nav.map((n, i) => n.header ? (
              <div key={`h${i}`} className="side-head">{n.label}</div>
            ) : (
              <button key={n.id} className="side-item" aria-current={n.id === page ? "page" : undefined} onClick={() => go(n.id!)}>
                {n.icon && <n.icon />}{n.label}
              </button>
            ))}
          </nav>
          <div className="side-foot">
            <div className="side-user">
              <span className="side-ava">{ws === "ops" ? "ز" : (merchant?.[0] ?? "پ")}</span>
              <div style={{ minWidth: 0 }}>
                <div className="u-name num">{ws === "ops" ? "تیم عملیات" : merchant}</div>
                <div className="u-role">{ws === "ops" ? "مرکز کنترل" : `${mkey?.category_title ?? "پذیرنده"}`}</div>
              </div>
            </div>
            <button className="side-btn" onClick={onLogout}>خروج از حساب</button>
          </div>
        </aside>
      )}

      <div className="content">
        <header className="topbar">
          <div className="topbar-in">
            {narrow && <ZMark size={26} />}
            <div style={{ minWidth: 0 }}>
              <div className="t-title">{current.label}</div>
              <div className="t-sub">{current.sub}</div>
            </div>
            <div className="t-right">
              {ws === "merchant" && meta && (
                <select className="btn num" value={merchant} onChange={(e) => setMerchant(e.target.value)} aria-label="پذیرنده"
                        style={{ maxWidth: 190 }}>
                  {meta.demo.length > 0 && (
                    <optgroup label="پیشنهاد برای بررسی">
                      {meta.demo.map((d) => <option key={d.merchant_key} value={d.merchant_key}>{d.merchant_key} — {d.why}</option>)}
                    </optgroup>
                  )}
                  <optgroup label="همه پذیرندگان">
                    {meta.merchants.slice(0, 200).map((m) => <option key={m.merchant_key} value={m.merchant_key}>{m.merchant_key} · {m.category_title}</option>)}
                  </optgroup>
                </select>
              )}
              <div className="seg" role="group" aria-label="بازه زمانی">
                {presets.map((p) => (
                  <button key={p.id} aria-pressed={p.id === presetId} onClick={() => setPresetId(p.id)}>{p.short ?? p.label}</button>
                ))}
              </div>
              {narrow && <button className="btn" style={{ padding: "6px 10px", fontSize: "0.72rem" }} onClick={onLogout}>خروج</button>}
            </div>
          </div>
        </header>

        <main className="main" id="main">{current.el}</main>

        {narrow && (
          <nav className="bottomnav" aria-label="ناوبری موبایل">
            {items.map((n) => (
              <button key={n.id} className="bn-item" aria-current={n.id === page ? "page" : undefined} onClick={() => go(n.id!)}>
                {n.icon && <n.icon />}{n.short}
              </button>
            ))}
          </nav>
        )}
      </div>

      <EvidenceDrawer />
    </div>
  );
}

export default function App() {
  const [session, setSession] = useState<WS | null>(() => {
    try { const v = sessionStorage.getItem("zb_ws"); return v === "ops" || v === "merchant" ? v : null; } catch { return null; }
  });
  const login = (ws: WS) => { try { sessionStorage.setItem("zb_ws", ws); } catch { /* storage blocked */ } setSession(ws); };
  const logout = () => {
    try { sessionStorage.removeItem("zb_ws"); sessionStorage.removeItem("zb_token"); } catch { /* storage blocked */ }
    location.hash = "";
    setSession(null);
  };
  return (
    <AppProvider>
      {session ? <Shell workspace={session} onLogout={logout} /> : <Login onLogin={login} />}
    </AppProvider>
  );
}
