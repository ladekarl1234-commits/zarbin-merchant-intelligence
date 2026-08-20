import { useEffect, useState } from "react";
import { AppProvider, useApp } from "./ctx";
import { faDate } from "./fmt";
import EvidenceDrawer from "./components/EvidenceDrawer";
import {
  IconChat, IconDelta, IconFunnel, IconGauge, IconHome, IconPlug,
  IconScale, IconServer, IconShield, IconSpark, IconUsers,
} from "./components/ui";
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

type Route = { id: string; label: string; short: string; icon: (p: { className?: string }) => JSX.Element; el: JSX.Element; mobile?: boolean };

const MERCHANT: Route[] = [
  { id: "overview", label: "نمای کلی", short: "کلی", icon: IconHome, el: <Overview />, mobile: true },
  { id: "funnel", label: "قیف پرداخت", short: "قیف", icon: IconFunnel, el: <FunnelPage />, mobile: true },
  { id: "changes", label: "چه چیزی تغییر کرد؟", short: "تغییر", icon: IconDelta, el: <ChangesPage />, mobile: true },
  { id: "peers", label: "همتایان", short: "همتا", icon: IconScale, el: <PeersPage />, mobile: true },
  { id: "customers", label: "مشتریان", short: "مشتری", icon: IconUsers, el: <CustomersPage />, mobile: true },
  { id: "copilot", label: "بپرس", short: "بپرس", icon: IconChat, el: <CopilotPage />, mobile: true },
  { id: "quality", label: "کیفیت داده", short: "کیفیت", icon: IconShield, el: <QualityPage /> },
];

const OPS: Route[] = [
  { id: "overview", label: "نمای پلتفرم", short: "پلتفرم", icon: IconServer, el: <OpsOverview />, mobile: true },
  { id: "performance", label: "کارایی", short: "کارایی", icon: IconGauge, el: <OpsPerformance />, mobile: true },
  { id: "ai", label: "هوش مصنوعی", short: "AI", icon: IconSpark, el: <OpsAI />, mobile: true },
  { id: "sources", label: "منابع داده", short: "منابع", icon: IconPlug, el: <OpsSources />, mobile: true },
  { id: "copilot", label: "دستیار عملیات", short: "دستیار", icon: IconChat, el: <OpsCopilotPage />, mobile: true },
];

type WS = "merchant" | "ops";

function useRoute(): [WS, string, (ws: WS, page: string) => void] {
  const parse = (): [WS, string] => {
    const ops = location.hash.match(/#\/ops\/([\w-]+)/);
    if (ops) return ["ops", ops[1]];
    const m = location.hash.match(/#\/([\w-]+)/);
    return ["merchant", m?.[1] ?? "overview"];
  };
  const [state, setState] = useState<[WS, string]>(parse);
  useEffect(() => {
    const on = () => { setState(parse()); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  const go = (ws: WS, page: string) => { location.hash = ws === "ops" ? `#/ops/${page}` : `#/${page}`; };
  return [state[0], state[1], go];
}

function Shell() {
  const { meta, merchant, setMerchant, presetId, setPresetId, presets } = useApp();
  const [ws, page, go] = useRoute();
  const routes = ws === "ops" ? OPS : MERCHANT;
  const current = routes.find((r) => r.id === page) ?? routes[0];

  return (
    <div className="shell" data-workspace={ws}>
      <a href="#main" style={{ position: "absolute", insetInlineStart: -9999 }}>پرش به محتوا</a>
      <div className="topband">
        <div className="topband-in">
          <div className="mark">
            <span className="mark-dot" aria-hidden>ز</span>
            <span>
              زرین‌بین
              <small>{ws === "ops" ? "مرکز کنترل و عملیات" : "هوش کسب‌وکار پذیرندگان زرین‌پال"}</small>
            </span>
          </div>

          <div className="ws-switch" role="tablist" aria-label="انتخاب فضای کاری">
            <button role="tab" aria-selected={ws === "merchant"} className={`ws-btn ${ws === "merchant" ? "on" : ""}`}
                    onClick={() => go("merchant", "overview")}>فضای پذیرنده</button>
            <button role="tab" aria-selected={ws === "ops"} className={`ws-btn ${ws === "ops" ? "on" : ""}`}
                    onClick={() => go("ops", "overview")}>مرکز کنترل</button>
          </div>

          <div className="top-controls">
            {ws === "merchant" && (
              <>
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
              </>
            )}
            <label style={{ fontSize: "var(--fs-xs)", color: "#ffffff90" }} htmlFor="psel">بازه</label>
            <select id="psel" className="select" value={presetId} onChange={(e) => setPresetId(e.target.value)}>
              {presets.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
            </select>
          </div>
        </div>
        <nav className="tabs" aria-label="بخش‌ها">
          <div className="tabs-in">
            {routes.map((r) => (
              <button key={r.id} className="tab" aria-current={r.id === page ? "page" : undefined}
                      onClick={() => go(ws, r.id)}>
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
        {ws === "merchant"
          ? <button className="linklike" onClick={() => go("merchant", "quality")}>کیفیت داده</button>
          : <button className="linklike" onClick={() => go("ops", "sources")}>منابع داده</button>} · زرین‌بین
      </p>

      <nav className="bottomnav" aria-label="ناوبری موبایل">
        {routes.filter((r) => r.mobile).map((r) => {
          const Icon = r.icon;
          return (
            <button key={r.id} className="bn-item" aria-current={r.id === page ? "page" : undefined}
                    onClick={() => go(ws, r.id)}>
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
