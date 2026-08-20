import { useEffect, useState } from "react";
import { AppProvider, useApp } from "./ctx";
import { faDate } from "./fmt";
import EvidenceDrawer from "./components/EvidenceDrawer";
import { IconChat, IconDelta, IconFunnel, IconHome, IconScale, IconShield, IconUsers } from "./components/ui";
import Overview from "./pages/Overview";
import FunnelPage from "./pages/FunnelPage";
import CustomersPage from "./pages/CustomersPage";
import PeersPage from "./pages/PeersPage";
import ChangesPage from "./pages/ChangesPage";
import CopilotPage from "./pages/CopilotPage";
import QualityPage from "./pages/QualityPage";

const ROUTES = [
  { id: "overview", label: "نمای کلی", short: "کلی", icon: IconHome, el: <Overview />, mobile: true },
  { id: "funnel", label: "قیف پرداخت", short: "قیف", icon: IconFunnel, el: <FunnelPage />, mobile: true },
  { id: "changes", label: "چه چیزی تغییر کرد؟", short: "تغییر", icon: IconDelta, el: <ChangesPage />, mobile: true },
  { id: "peers", label: "همتایان", short: "همتا", icon: IconScale, el: <PeersPage />, mobile: true },
  { id: "customers", label: "مشتریان", short: "مشتری", icon: IconUsers, el: <CustomersPage />, mobile: true },
  { id: "copilot", label: "بپرس", short: "بپرس", icon: IconChat, el: <CopilotPage />, mobile: true },
  { id: "quality", label: "کیفیت داده", short: "کیفیت", icon: IconShield, el: <QualityPage />, mobile: false },
];

function useRoute(): [string, (r: string) => void] {
  const parse = () => location.hash.match(/#\/(\w+)/)?.[1] ?? "overview";
  const [route, setRoute] = useState(parse);
  useEffect(() => {
    const on = () => { setRoute(parse()); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return [route, (r) => { location.hash = `#/${r}`; }];
}

function Shell() {
  const { meta, merchant, setMerchant, presetId, setPresetId, presets } = useApp();
  const [route, go] = useRoute();
  const current = ROUTES.find((r) => r.id === route) ?? ROUTES[0];

  return (
    <div className="shell">
      <a href="#main" style={{ position: "absolute", insetInlineStart: -9999 }}>پرش به محتوا</a>
      <div className="topband">
        <div className="topband-in">
          <div className="mark">
            <span className="mark-dot" aria-hidden>ز</span>
            <span>
              زرین‌بین
              <small>هوش کسب‌وکار پذیرندگان زرین‌پال</small>
            </span>
          </div>
          <div className="top-controls">
            <label style={{ fontSize: "var(--fs-xs)", color: "#ffffff90" }} htmlFor="msel">پذیرنده</label>
            <select id="msel" className="select num" value={merchant} onChange={(e) => setMerchant(e.target.value)}>
              {meta?.demo.length ? (
                <optgroup label="پیشنهاد برای بررسی">
                  {meta.demo.map((d) => (
                    <option key={d.merchant_key} value={d.merchant_key}>{d.merchant_key} — {d.why}</option>
                  ))}
                </optgroup>
              ) : null}
              <optgroup label="همه پذیرندگان (به ترتیب فروش)">
                {meta?.merchants.slice(0, 200).map((m) => (
                  <option key={m.merchant_key} value={m.merchant_key}>{m.merchant_key} · {m.category_title}</option>
                ))}
              </optgroup>
            </select>
            <label style={{ fontSize: "var(--fs-xs)", color: "#ffffff90" }} htmlFor="psel">بازه</label>
            <select id="psel" className="select" value={presetId} onChange={(e) => setPresetId(e.target.value)}>
              {presets.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
            </select>
          </div>
        </div>
        <nav className="tabs" aria-label="بخش‌ها">
          <div className="tabs-in">
            {ROUTES.map((r) => (
              <button key={r.id} className="tab" aria-current={r.id === route ? "page" : undefined}
                      onClick={() => go(r.id)}>
                {r.label}
              </button>
            ))}
          </div>
        </nav>
      </div>

      <main className="main" id="main">
        {current.el}
      </main>

      <p className="footer-note num">
        {meta?.notes.currency} داده: دیتاست چالش زرین‌پال، {meta ? `${faDate(meta.range.from)} تا ${faDate(meta.range.to)}` : ""} ·
        <button className="linklike" onClick={() => go("quality")}>کیفیت داده</button> · زرین‌بین
      </p>

      <nav className="bottomnav" aria-label="ناوبری موبایل">
        {ROUTES.filter((r) => r.mobile).map((r) => {
          const Icon = r.icon;
          return (
            <button key={r.id} className="bn-item" aria-current={r.id === route ? "page" : undefined}
                    onClick={() => go(r.id)}>
              <Icon />
              {r.short}
            </button>
          );
        })}
      </nav>

      <EvidenceDrawer />
    </div>
  );
}

export default function App() {
  return (
    <AppProvider>
      <Shell />
    </AppProvider>
  );
}
