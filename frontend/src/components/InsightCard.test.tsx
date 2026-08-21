// ZB-043 smoke test: InsightCard renders title/impact and — the specific regression this
// guards (ZB-013, "copilot prints a transaction count as rial") — a count-denominated card
// must show its impact in تراکنش (transactions), never as a compact rial magnitude
// (میلیون/میلیارد...), the way a money card does.
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { InsightCard as Card } from "../api";
import InsightCard from "./InsightCard";

vi.mock("../ctx", () => ({
  useApp: () => ({ merchant: "M1", openEvidence: () => {} }),
}));

function moneyCard(overrides: Partial<Card> = {}): Card {
  return {
    id: "inbank_gap", kind: "inbank_gap", card_type: "opportunity",
    title_fa: "رهاشدن در صفحه بانک بیش از همتایان",
    observation_fa: "obs", diagnosis_fa: "diag", action_fa: "act",
    impact_low: 20_000_000, impact_mid: 30_000_000, impact_high: 40_000_000,
    impact_label_fa: "برآورد فرصت",
    confidence: "medium", effort: "medium", n: 500, score: 12345,
    evidence: [],
    ...overrides,
  };
}

function countCard(overrides: Partial<Card> = {}): Card {
  return {
    id: "psp_friction", kind: "psp_friction", card_type: "opportunity",
    title_fa: "درگاه PSP-B به‌طور محسوس ضعیف‌تر از بقیه عمل می‌کند",
    observation_fa: "obs", diagnosis_fa: "diag", action_fa: "act",
    impact_low: 178, impact_high: 356, impact_label_fa: "برآورد تلاش‌های قابل نجات (تعداد تراکنش)",
    impact_is_count: true,
    confidence: "medium", effort: "easy", n: 900, score: 214,
    evidence: [],
    ...overrides,
  };
}

describe("InsightCard", () => {
  it("renders the title and a compact rial magnitude for a money card", () => {
    render(<InsightCard card={moneyCard()} rank={1} />);
    expect(screen.getByText("رهاشدن در صفحه بانک بیش از همتایان")).toBeInTheDocument();
    // money cards render via rial(v, false) — a compact magnitude with no "ریال"/"تراکنش" suffix
    const amount = screen.getByText(/میلیون/, { selector: ".amount" });
    expect(amount.textContent).not.toMatch(/تراکنش/);
  });

  it("renders a count card's impact in تراکنش, never as a rial magnitude (ZB-013 regression)", () => {
    render(<InsightCard card={countCard()} rank={2} />);
    const amount = screen.getByText(/تراکنش/, { selector: ".amount" });
    expect(amount.textContent).toMatch(/تراکنش/);
    expect(amount.textContent).not.toMatch(/میلیون|میلیارد|ریال/);
  });

  it("shows the priority rank for an opportunity and '!' for an alert", () => {
    render(<InsightCard card={moneyCard()} rank={3} />);
    expect(screen.getByLabelText("اولویت 3")).toBeInTheDocument();
    render(<InsightCard card={moneyCard({ card_type: "alert", id: "gmv_change", kind: "gmv_change" })} rank={1} />);
    expect(screen.getByLabelText("هشدار")).toBeInTheDocument();
  });
});
