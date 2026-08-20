# Spec — Implement Zarbin.dc.html redesign

Source: Claude Design project "Redesign ZarinPal Product Interface" → `Zarbin.dc.html`.
Maps to (github.md): frontend App.tsx, theme.css, all merchant pages, InsightCard, charts,
Copilot, EvidenceDrawer, fmt.ts, api.ts.

## What changes (design → code)
- **New visual language**: bg #f6f6f7, ink #16161d, blue accent #2333e0/#2029e8, brand #ffd500,
  good #0d8a5f, bad #c43a26, warn #8a6100; 14px cards, 12px inputs, 999px pills; subtle shadows;
  Vazirmatn (already bundled).
- **Login gate** (phone → 5-digit OTP → app). Demo/client-side only (no auth backend); the design
  itself routes by role afterward. OTP is a visual step; "logout" returns to login.
- **Left sidebar shell** (248px, sticky) replacing the top-band tabs: grouped nav —
  دستیار(گفتگو), تحلیل‌ها(نمای کلی/مسیر پرداخت/چه چیزی تغییر کرد؟/مقایسه با مشابه‌ها/مشتریان),
  شفافیت(کیفیت داده); active item = #fff8d9 bg + inset 3px #ffd500 + bold. User card + logout at bottom.
- **Header**: page title/sub + period segmented control (کل دوره/۹۰ روز/۳۰ روز; active = ink bg).
- **Chat-first landing** (default page = گفتگو): hero "از کسب و کارت چه خبر؟؟", glance KPI strip
  (real overview data), prompt cards, sticky composer with mic + بپرس → REAL grounded copilot.
- **De-jargoned copy**: نرخ تکمیل پرداخت (=conv), مسیر پرداخت (=funnel), مقایسه با مشابه‌ها (=peers).
- **Rich tooltips** (3-part: یعنی چه؟ / چرا مهم است؟ / چطور تفسیر کنم؟) via a TIPS dictionary,
  fixed dark popover; wired to KPIs and key metric labels.
- **Evidence drawer**: left-side, metric/def/formula/spec/SQL/caveat + source-sessions button
  (already exists; restyle to new tokens).
- **Mobile (<860px)**: sidebar hidden → 6-item bottom nav; main padding-bottom 88px.

## Preserve (do not break)
- All data wiring: pages keep their `useData`/`useAdmin` hooks and the real API.
- The Control Center (built previously, not in this mockup): keep reachable + inherit new tokens.
- Deterministic/grounded copilot, evidence lineage, all analytics invariants, 56 backend tests.

## Acceptance
1. `uv run zarin` serves; app opens on the login screen; proceeding lands on the chat-first page.
2. Sidebar nav switches pages; period control works; chat uses the REAL copilot (grounded).
3. Glance/overview KPIs show REAL data from `/api/overview`.
4. Rich tooltips open on hover + keyboard focus + tap; evidence drawer shows real SQL.
5. Both surfaces render on desktop 1440×900 and mobile 390×844; frontend build clean; 0 console errors.
6. Backend untouched → 56 tests still pass.

## Non-goals
Real phone/OTP auth backend (demo gate only); replacing the deterministic copilot with the mockup's
canned answers (we wire the real one instead); pixel-identical reproduction of every mockup number
(mockup data is illustrative — real API data replaces it).
