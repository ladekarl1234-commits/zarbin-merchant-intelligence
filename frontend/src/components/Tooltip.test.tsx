// ZB-043 smoke test: the Term tooltip must open on keyboard focus (not just hover/click — a
// keyboard-only user has no hover) and wire aria-describedby to the opened popover's id, per
// ZB-033's a11y fix note.
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Term } from "./Tooltip";

describe("Term", () => {
  it("has no aria-describedby before it is opened", () => {
    render(<Term label="نرخ تبدیل" tip="conv" />);
    const trigger = screen.getByRole("button", { name: /توضیح/ });
    expect(trigger).not.toHaveAttribute("aria-describedby");
  });

  it("opens the tooltip on focus and wires aria-describedby to the rendered tooltip's id", () => {
    render(<Term label="نرخ تبدیل" tip="conv" />);
    const trigger = screen.getByRole("button", { name: /توضیح/ });
    fireEvent.focus(trigger);
    const tip = screen.getByRole("tooltip");
    expect(trigger).toHaveAttribute("aria-describedby", tip.id);
    expect(tip).toHaveTextContent("نرخ تکمیل پرداخت"); // TIPS.conv.title
  });

  it("closes on blur, dropping aria-describedby again", () => {
    render(<Term label="نرخ تبدیل" tip="conv" />);
    const trigger = screen.getByRole("button", { name: /توضیح/ });
    fireEvent.focus(trigger);
    expect(screen.getByRole("tooltip")).toBeInTheDocument();
    fireEvent.blur(trigger);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    expect(trigger).not.toHaveAttribute("aria-describedby");
  });

  it("renders the plain label with no popover for an empty tip", () => {
    render(<Term label="پلیک" tip="" />);
    expect(screen.getByText("پلیک")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("treats an unrecognized tip string as a simple one-liner, not a rich 3-part tip", () => {
    render(<Term label="پلیک" tip="یک توضیح ساده" />);
    fireEvent.focus(screen.getByRole("button", { name: /توضیح/ }));
    const tip = screen.getByRole("tooltip");
    expect(tip).toHaveTextContent("یک توضیح ساده");
    expect(tip).not.toHaveTextContent("یعنی چه؟");
  });
});
