import { useId, useState } from "react";

/** A term with a progressive-disclosure explanation.
 *  Accessible: the bubble shows on mouse hover, keyboard focus (focus-within), and tap
 *  (data-open toggle). Escape closes. The `?` is a real button so keyboard users reach it. */
export function Term({ label, tip }: { label: React.ReactNode; tip: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <span className="term">
      <span>{label}</span>
      <span className="tip" data-open={open || undefined} onMouseLeave={() => setOpen(false)}>
        <button type="button" className="tip-btn" aria-label="توضیح بیشتر"
                aria-expanded={open} aria-describedby={id}
                onClick={() => setOpen((o) => !o)}
                onKeyDown={(e) => e.key === "Escape" && setOpen(false)}>؟</button>
        <span role="tooltip" id={id} className="tip-bubble">{tip}</span>
      </span>
    </span>
  );
}
