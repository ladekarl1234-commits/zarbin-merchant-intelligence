# Plan — Dual-Surface Platform

## Batch 1 — Backend platform (Python, zero new deps: stdlib urllib)
- `zarin/config.py` += AI/GA4/telemetry config (env-driven).
- `zarin/ai/`: contract, models(free-policy), provider(OpenRouter via urllib + Null), safe_context, telemetry, gateway.
- `zarin/copilot.py` → v2: `plan()` intent+tools → deterministic result → gateway.explain() → grounded answer + contract.
- `zarin/obs.py`: request telemetry store + ASGI middleware (P50/P95/P99, error rate, throughput).
- `zarin/sources/`: base(adapter+registry), zarinpal, ga4(gated), insights(cross-source).
- `zarin/control.py`: platform / performance / ai-ops / sources aggregations (decision-oriented).
- `zarin/ai/eval/`: cases, runner, __main__.
- `zarin/api.py` += middleware, `/api/admin/*`, copilot feedback, copilot v2 wiring.
- Tests: safe_context, models(free policy), gateway(fallback+grounding+no-key), control, sources(ga4 unconfigured), ai_eval.
- Gate: run pytest + ruff. Commit `feat: grounded AI gateway, telemetry, sources, control center API`.

## Batch 2 — Frontend dual-surface
- `ctx.tsx`: add `workspace` ('merchant'|'ops'); route prefixes.
- `App.tsx`: workspace switch in top band; render merchant shell or ops shell.
- `components/Tooltip.tsx`: accessible progressive-disclosure info affordance.
- `components/Copilot.tsx`: shared chat w/ voice-to-text (Web Speech + fallback), feedback, grounded badge.
- `ops/`: OpsOverview, OpsPerformance, OpsAI, OpsSources, OpsCopilot; `ops.ts` types+client.
- `theme.css`: ops surface tokens (denser, operational, distinct from merchant).
- Build `tsc --noEmit && vite build` → copy to zarin/static (vite outDir). Commit `feat: dual merchant + control center workspaces, voice copilot, tooltips`.

## Batch 3 — Docs
memory.md, docs/ADR/0001..0004, DEPLOYMENT_SPEC, PLATFORM_BOOK, CONTRIBUTING, README rebuild, DESIGN update, ARCHITECTURE/ANALYTICS update. Commit `docs: ADRs, deployment spec, platform book, memory, contributing, README`.

## Batch 4 — Validate + review + screenshots + push
Run server, browser QA desktop 1440x900 + mobile 390x844 both surfaces, screenshots, independent review, fix, final git verify.
