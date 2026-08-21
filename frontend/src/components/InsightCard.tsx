import { useState } from "react";
import type { InsightCard as Card } from "../api";
import { useApp } from "../ctx";
import { faNum, rial } from "../fmt";
import { ConfChip, EvBtn } from "./ui";

// Map an insight kind to the single session outcome whose rows are its evidence.
const KIND_SAMPLE: Record<string, string> = {
  paid_unverified: "paid_unverified",
  no_attempt_gap: "no_attempt",
  inbank_gap: "abandoned_inbank",
};

const EFFORT_FA: Record<string, string> = { easy: "اقدام سریع", medium: "اقدام متوسط", hard: "پروژه بلندمدت" };

// ZB-027: ranked action cards were terminal — no way to act on them from here. Route each card
// kind to the page with its supporting data/visualization, so «مشاهده» is a real next step.
const CARD_TARGET: Record<string, string> = {
  paid_unverified: "funnel",
  no_attempt_gap: "funnel",
  inbank_gap: "funnel",
  high_value_friction: "funnel",
  psp_friction: "funnel",
  recovery_gap: "peers",     // peer-comparison card — see the percentile on the peers page
  repeat_gap: "customers",
  concentration: "customers",
  gmv_change: "changes",
};
const TARGET_LABEL: Record<string, string> = {
  funnel: "مشاهده در مسیر پرداخت",
  customers: "مشاهده در مشتریان",
  peers: "مشاهده در مقایسه با مشابه‌ها",
  changes: "مشاهده در چه چیزی تغییر کرد؟",
};

type CardStatus = "done" | "skip";
// ponytail: plain localStorage, no sync across tabs — fine for a per-merchant personal checklist.
function statusKey(merchant: string) { return `zb_card_status:${merchant}`; }
function loadStatuses(merchant: string): Record<string, CardStatus> {
  try { return JSON.parse(localStorage.getItem(statusKey(merchant)) || "{}"); } catch { return {}; }
}
function saveStatus(merchant: string, id: string, status: CardStatus | null) {
  const cur = loadStatuses(merchant);
  if (status) cur[id] = status; else delete cur[id];
  try { localStorage.setItem(statusKey(merchant), JSON.stringify(cur)); } catch { /* storage blocked */ }
}

export default function InsightCard({ card, rank }: { card: Card; rank: number }) {
  const { merchant } = useApp();
  const [, setTick] = useState(0); // localStorage isn't reactive — bump this to re-read after a write
  const status = loadStatuses(merchant)[card.id] ?? null;
  const setCardStatus = (s: CardStatus | null) => { saveStatus(merchant, card.id, s); setTick((x) => x + 1); };
  const target = CARD_TARGET[card.kind];
  const hasInterval = card.impact_high > 0 && card.impact_high !== card.impact_low;
  const isAlert = card.card_type === "alert";
  const amount = (v: number) => (card.impact_is_count ? `${faNum(v)} تراکنش` : rial(v, false));
  const point = card.impact_mid != null && hasInterval
    ? (card.impact_is_count ? amount(card.impact_mid) : rial(card.impact_mid, false))
    : hasInterval
      ? `${amount(card.impact_low)} تا ${card.impact_is_count ? amount(card.impact_high) : rial(card.impact_high, false)}`
      : (card.impact_is_count ? amount(card.impact_high) : rial(card.impact_high, false));

  return (
    <article className={`insight${isAlert ? " insight-alert" : ""}`} style={{ opacity: status === "done" ? 0.6 : 1 }}>
      <span className="rank" aria-label={isAlert ? "هشدار" : `اولویت ${rank}`}>
        {isAlert ? "!" : faNum(rank)}
      </span>
      <div className="body">
        <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
          <h3>{card.title_fa}</h3>
          {card.impact_high > 0 && <span className="amount num">{point}</span>}
          {status === "done" && <span className="chip chip-good">انجام شد</span>}
        </div>
        {card.impact_high > 0 && (
          <div className="num" style={{ fontSize: "var(--fs-xs)", color: "var(--ink-3)" }}>
            {card.impact_label_fa}
            {card.impact_mid != null && hasInterval &&
              ` (بین ${amount(card.impact_low)} تا ${card.impact_is_count ? amount(card.impact_high) : rial(card.impact_high, false)})`}
          </div>
        )}

        <div className="row"><b>مشاهده:</b><span className="num">{card.observation_fa}</span></div>
        <div className="row"><b>تشخیص:</b><span>{card.diagnosis_fa}</span></div>
        <div className="row"><b>اقدام:</b><span>{card.action_fa}</span></div>

        <footer>
          <ConfChip level={card.confidence} />
          <span className="chip chip-mute">{EFFORT_FA[card.effort] ?? card.effort}</span>
          {card.n_peers != null && card.n_peers < 8 && (
            <span className="chip chip-warn num">مقایسه با {faNum(card.n_peers)} همتا — نامطمئن</span>
          )}
          {card.capped && <span className="chip chip-warn">سقف واقع‌بینانه</span>}
          <span className="chip chip-mute num">نمونه: {faNum(card.n)}</span>
          <span style={{ marginInlineStart: "auto" }}>
            <EvBtn title={card.title_fa} items={card.evidence} sampleOutcome={KIND_SAMPLE[card.kind]} label="این عدد از کجا آمد؟" />
          </span>
        </footer>

        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginTop: 10 }}>
          {target && (
            <button type="button" className="btn" style={{ padding: "6px 14px", fontSize: "0.76rem" }}
                    onClick={() => { location.hash = `#/${target}`; }}>
              {TARGET_LABEL[target]}
            </button>
          )}
          <span className="vote" role="group" aria-label="وضعیت این اقدام برای شما">
            <button type="button" className={`vote-btn ${status === "done" ? "on" : ""}`}
                    aria-pressed={status === "done"} onClick={() => setCardStatus(status === "done" ? null : "done")}>
              انجام شد
            </button>
            <button type="button" className={`vote-btn ${status === "skip" ? "on" : ""}`}
                    aria-pressed={status === "skip"} onClick={() => setCardStatus(status === "skip" ? null : "skip")}>
              فعلاً نه
            </button>
          </span>
        </div>
      </div>
    </article>
  );
}
