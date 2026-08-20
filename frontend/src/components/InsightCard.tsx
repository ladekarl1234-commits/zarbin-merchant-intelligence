import type { InsightCard as Card } from "../api";
import { faNum, rial } from "../fmt";
import { ConfChip, EvBtn } from "./ui";

// Map an insight kind to the single session outcome whose rows are its evidence.
// Kinds that span multiple outcomes (a mix, or a change) are NOT keyed here → the
// drawer hides the "source sessions" block rather than showing non-evidence rows.
const KIND_SAMPLE: Record<string, string> = {
  paid_unverified: "paid_unverified",
  no_attempt_gap: "no_attempt",
  inbank_gap: "abandoned_inbank",
  // high_value_friction, recovery_gap, repeat_gap, concentration, gmv_change, psp_friction:
  // intentionally omitted — no single outcome represents them.
};

const EFFORT_FA: Record<string, string> = { easy: "اقدام سریع", medium: "اقدام متوسط", hard: "پروژه بلندمدت" };

export default function InsightCard({ card, rank }: { card: Card; rank: number }) {
  const hasInterval = card.impact_high > 0 && card.impact_high !== card.impact_low;
  const isAlert = card.card_type === "alert";
  const amount = (v: number) =>
    card.impact_is_count ? `${faNum(v)} تراکنش` : rial(v, false);
  return (
    <article className={`insight${isAlert ? " insight-alert" : ""}`}>
      <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
        <span className={`rank${isAlert ? " rank-alert" : ""}`} aria-label={isAlert ? "هشدار" : `اولویت ${rank}`}>
          {isAlert ? "!" : faNum(rank)}
        </span>
        <h3>{card.title_fa}</h3>
      </div>

      <div className="impact">
        {card.impact_high > 0 ? (
          <>
            <span style={{ fontSize: "var(--fs-xs)", color: "var(--ink-2)", width: "100%" }}>{card.impact_label_fa}</span>
            <span className="amount num">
              {hasInterval
                ? `${amount(card.impact_low)} تا ${card.impact_is_count ? amount(card.impact_high) : rial(card.impact_high)}`
                : (card.impact_is_count ? amount(card.impact_high) : rial(card.impact_high))}
            </span>
          </>
        ) : (
          <span className="num" style={{ fontSize: "var(--fs-m)", fontWeight: 700 }}>{card.impact_label_fa}</span>
        )}
      </div>

      <div className="row"><b>مشاهده:</b><span className="num">{card.observation_fa}</span></div>
      <div className="row"><b>تشخیص:</b><span>{card.diagnosis_fa}</span></div>
      <div className="row"><b>اقدام پیشنهادی:</b><span>{card.action_fa}</span></div>

      <footer>
        <ConfChip level={card.confidence} />
        <span className="chip chip-mute">{EFFORT_FA[card.effort] ?? card.effort}</span>
        {card.n_peers != null && card.n_peers < 8 && (
          <span className="chip chip-warn num">مقایسه با {faNum(card.n_peers)} همتا — نامطمئن</span>
        )}
        {card.capped && <span className="chip chip-warn">سقف واقع‌بینانه</span>}
        <span className="chip chip-mute num">نمونه: {faNum(card.n)}</span>
        <span style={{ marginInlineStart: "auto" }}>
          <EvBtn title={card.title_fa} items={card.evidence} sampleOutcome={KIND_SAMPLE[card.kind]}
                 label="این عدد از کجا آمد؟" />
        </span>
      </footer>
    </article>
  );
}
