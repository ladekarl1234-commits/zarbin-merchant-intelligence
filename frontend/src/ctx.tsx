import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { Evidence, Meta } from "./api";
import { get } from "./api";

export type Period = { f: string; t: string; cf?: string; ct?: string; label: string };

type Ctx = {
  meta: Meta | null;
  merchant: string;
  setMerchant: (m: string) => void;
  period: Period;
  setPresetId: (id: string) => void;
  presetId: string;
  presets: { id: string; label: string; short?: string }[];
  openEvidence: (title: string, items: Evidence[], sampleOutcome?: string) => void;
  drawer: { title: string; items: Evidence[]; sampleOutcome?: string } | null;
  closeEvidence: () => void;
};

const AppCtx = createContext<Ctx>(null as unknown as Ctx);
export const useApp = () => useContext(AppCtx);

function addDays(iso: string, days: number): string {
  const d = new Date(iso + "T12:00:00");
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [merchant, setMerchant] = useState<string>("");
  const [presetId, setPresetId] = useState("all");
  const [drawer, setDrawer] = useState<Ctx["drawer"]>(null);

  useEffect(() => {
    get<Meta>("meta", {}).then((m) => {
      setMeta(m);
      const first = m.demo[0]?.merchant_key ?? m.merchants[0]?.merchant_key;
      if (first) setMerchant((cur) => cur || first);
    });
  }, []);

  const presets = useMemo(() => [
    { id: "all", label: "کل دوره (۶ ماه)", short: "کل دوره" },
    { id: "d90", label: "۹۰ روز آخر", short: "۹۰ روز" },
    { id: "d30", label: "۳۰ روز آخر", short: "۳۰ روز" },
  ], []);

  const period = useMemo<Period>(() => {
    const lo = meta?.range.from ?? "2026-01-01";
    const hi = meta?.range.to ?? "2026-06-30";
    if (presetId === "d30") {
      const f = addDays(hi, -29);
      return { f, t: hi, cf: addDays(f, -30), ct: addDays(f, -1), label: "۳۰ روز آخر" };
    }
    if (presetId === "d90") {
      const f = addDays(hi, -89);
      return { f, t: hi, cf: addDays(f, -90), ct: addDays(f, -1), label: "۹۰ روز آخر" };
    }
    return { f: lo, t: hi, label: "کل دوره" };
  }, [meta, presetId]);

  const openEvidence = useCallback((title: string, items: Evidence[], sampleOutcome?: string) => {
    setDrawer({ title, items, sampleOutcome });
  }, []);
  const closeEvidence = useCallback(() => setDrawer(null), []);

  const value = useMemo(() => ({
    meta, merchant, setMerchant, period, presetId, setPresetId, presets,
    openEvidence, drawer, closeEvidence,
  }), [meta, merchant, period, presetId, presets, openEvidence, drawer, closeEvidence]);

  return <AppCtx.Provider value={value}>{children}</AppCtx.Provider>;
}

/** Control-Center fetching. `usePeriod` sends the selected window (platform/sources);
 *  global telemetry endpoints (performance/ai-ops/eval) omit it. */
export function useAdmin<T>(path: string, opts?: { usePeriod?: boolean }) {
  const { period } = useApp();
  const [state, setState] = useState<{ data: T | null; loading: boolean; error: string | null }>({
    data: null, loading: true, error: null,
  });
  const usePeriod = opts?.usePeriod ?? false;
  const key = JSON.stringify([path, usePeriod ? [period.f, period.t] : null]);
  useEffect(() => {
    let alive = true;
    setState((s) => ({ ...s, loading: true, error: null }));
    get<T>(path, usePeriod ? { f: period.f, t: period.t } : {})
      .then((d) => alive && setState({ data: d, loading: false, error: null }))
      .catch((e) => alive && setState({ data: null, loading: false, error: String(e) }));
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return state;
}

/** data fetching bound to merchant+period */
export function useData<T>(path: string, extra?: Record<string, string | undefined>) {
  const { merchant, period } = useApp();
  const [state, setState] = useState<{ data: T | null; loading: boolean; error: string | null }>({
    data: null, loading: true, error: null,
  });
  const key = JSON.stringify([path, merchant, period.f, period.t, extra]);
  useEffect(() => {
    if (!merchant) return;
    let alive = true;
    setState((s) => ({ ...s, loading: true, error: null }));
    get<T>(path, { m: merchant, f: period.f, t: period.t, ...extra })
      .then((d) => alive && setState({ data: d, loading: false, error: null }))
      .catch((e) => alive && setState({ data: null, loading: false, error: String(e) }));
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return state;
}
