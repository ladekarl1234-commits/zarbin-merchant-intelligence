// API client + shared types (mirrors zarin/api.py responses).

export type Evidence = {
  metric_id: string; name_fa: string; definition_fa: string; formula: string;
  grain: string; caveats: string[]; sql: string; params: Record<string, unknown>;
  n: number | null; period: string | null; computed_at: string;
  note_fa?: string; method_fa?: string; rule_fa?: string;
};

export type Meta = {
  range: { from: string; to: string };
  merchants: { merchant_key: string; category_title: string; sessions: number; verified: number; gmv: number; active_months: number }[];
  demo: { merchant_key: string; why: string }[];
  notes: { currency: string; fee: string; customer: string };
};

export type Overview = {
  period: { from: string; to: string };
  kpis: {
    gmv: number; verified: number; sessions: number; conv: number | null;
    median_ticket: number | null; customers: number; paid_unverified: number;
    paid_unverified_amount: number; fee_index_sum: number;
  };
  previous: { gmv: number; verified: number; sessions: number; conv: number | null } | null;
  daily: { d: string; sessions: number; verified: number; gmv: number; conv: number | null }[];
  evidence: Record<string, Evidence>;
};

export type InsightCard = {
  id: string; kind: string; title_fa: string; observation_fa: string; diagnosis_fa: string;
  action_fa: string; impact_low: number; impact_high: number; impact_label_fa: string;
  confidence: "high" | "medium" | "low"; effort: string; n: number; score: number;
  risk_gmv?: number; evidence: Evidence[];
};

export type Funnel = {
  stages: { id: string; label_fa: string; n: number }[];
  outcomes: Record<string, number>;
  rates: Record<string, number | null>;
  recovery: { first_fail_pool: number; recovered: number; recovery_rate: number | null; recovered_gmv: number };
  hours: { hour: number; sessions: number; verified: number }[];
  amount_bands: { band: number; lo: number; hi: number; sessions: number; conv: number }[];
  psp: { psp_code: string; attempts: number; ok_rate: number }[];
  fail_codes: { code: string; n: number }[];
  evidence: Record<string, Evidence>;
};

export type Customers = {
  summary: {
    customers: number; new_customers: number; txns: number; repeat_txns: number;
    gmv: number; repeat_gmv: number; repeat_customers: number;
  };
  concentration: { top5_share: number | null; n: number };
  interval: { median_days: number | null; n: number };
  cohorts: { first_month: string; k: number; active: number; cohort_size: number }[];
  dormant: { n: number; gmv: number };
  evidence: Record<string, Evidence>;
};

export type Peers = {
  group: { n: number; rule_fa: string; level: string; sufficient: boolean; me: Record<string, unknown> };
  rows: {
    metric: string; value: number | null; suppressed: boolean;
    p25?: number; p50?: number; p75?: number; percentile?: number; n_peers?: number; higher_better?: boolean;
  }[];
  evidence: Evidence;
};

export type Changes = {
  before: { from: string; to: string; sessions: number; conv: number; ticket: number; gmv: number };
  after: { from: string; to: string; sessions: number; conv: number; ticket: number; gmv: number };
  delta_gmv: number; decomposable: boolean;
  contrib: { sessions?: number; conv?: number; ticket?: number };
  conv_drivers: Record<string, number>;
  evidence: Evidence;
};

export type CopilotAnswer = { answer_fa: string; intent: string; evidence: Evidence[]; note_fa: string };

export type Quality = {
  outcomes: { outcome: string; n: number; amount: number | null }[];
  concentration: { top5: number; n: number };
  anomalies: { verified_wo_ok_try: number; reversed_sessions: number };
  rules_fa: string[];
};

export type SessionSample = {
  rows: { session_key: number; d: string; amount: number; outcome: string; n_tries: number;
          first_try_status: string | null; last_try_status: string | null; win_psp: string | null }[];
  total: number; note_fa: string;
};

export async function get<T>(path: string, params: Record<string, string | undefined>): Promise<T> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v != null && v !== "") qs.set(k, v);
  const res = await fetch(`/api/${path}?${qs}`);
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json();
}
