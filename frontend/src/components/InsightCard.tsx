import type { InsightCard as Card } from "../api";
import { faNum, rial } from "../fmt";
import { ConfChip, EvBtn } from "./ui";

const KIND_SAMPLE: Record<string, string | undefined> = {
  paid_unverified: "paid_unverified",
  no_attempt_gap: "no_attempt",
  inbank_gap: "abandoned_inbank",
  high_value_friction: undefined,
  recovery_gap: undefined,
};

const EFFORT_FA: Record<string, string> = { easy: "اقدام سریع", medium: "اقدام متوسط", hard: "پروژه بلندمدت" };

export default function InsightCard({ card, rank }: { card: Card; rank: number }) {
  const hasInterval = card.impact_high > 0 && card.impact_high !== card.impact_low;
  return (
    <article className="insight">
      <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
        <span className="rank" aria-label={`اولویت ${rank}`}>{faNum(rank)}</span>
        <h3>{card.title_fa}</h3>
      </div>

      <div className="impact">
        {card.impact_high > 0 ? (
          <>
            <span style={{ fontSize: "var(--fs-xs)", color: "var(--ink-2)", width: "100%" }}>{card.impact_label_fa}</span>
            <span className="amount num">
              {hasInterval ? `${rial(card.impact_low, false)} تا ${rial(card.impact_high)}` : rial(card.impact_high)}
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
        <span className="chip chip-mute num">نمونه: {faNum(card.n)}</span>
        <span style={{ marginInlineStart: "auto" }}>
          <EvBtn title={card.title_fa} items={card.evidence} sampleOutcome={KIND_SAMPLE[card.kind]}
                 label="این عدد از کجا آمد؟" />
        </span>
      </footer>
    </article>
  );
}
