"""Explainable peer benchmarking.

Peer rule (documented in docs/ANALYTICS.md, shown verbatim in the UI):
1. same category;
2. similar daily sales scale: gmv_per_day within ×¼ … ×4 of the merchant;
3. similar ticket: median_ticket within ×⅓ … ×3;
4. peer pool only includes merchants with ≥ 500 sessions (noise floor).
If the band yields < PREFERRED_PEERS peers, drop rule 3; if still short, use the whole
category. If fewer than MIN_PEERS remain, benchmarks are suppressed — never fabricated.
"""
from __future__ import annotations

from .config import MIN_PEERS, PREFERRED_PEERS
from .db import q, q1
from .registry import evidence

POOL_SQL = "SELECT * FROM merchant_stats WHERE sessions >= 500"

# metric -> (column expr over period-aggregated merchant_daily, higher_is_better)
BENCH_METRICS = {
    "conv": ("sum(verified)/nullif(sum(sessions),0)", True),
    "first_try_conv": ("sum(first_try_verified)/nullif(sum(sessions),0)", True),
    "no_attempt_rate": ("sum(no_attempt)/nullif(sum(sessions),0)", False),
    "inbank_abandon_rate": ("sum(abandoned_inbank)/nullif(sum(sessions),0)", False),
    # same denominator as the merchant's own recovery_rate (analytics.funnel): first-fail pool
    "recovery_rate": ("sum(recovered)/nullif(sum(attempted)-sum(first_try_ok),0)", True),
}


def peer_group(m: str) -> dict:
    me = q1("SELECT * FROM merchant_stats WHERE merchant_key=$m", {"m": m})
    if not me:
        return {"peers": [], "n": 0, "rule_fa": "پذیرنده یافت نشد", "level": "none", "me": {}}
    levels = [
        ("scale+ticket",
         (f"({POOL_SQL.split('WHERE')[1]}) AND category_id = $cat AND merchant_key != $m "
          "AND gmv_per_day BETWEEN $g/4 AND $g*4 AND median_ticket BETWEEN $tk/3 AND $tk*3"),
         "هم‌صنف، با فروش روزانه در محدوده ¼ تا ۴ برابر و مبلغ متوسط تراکنش در محدوده ⅓ تا ۳ برابر شما"),
        ("scale",
         (f"({POOL_SQL.split('WHERE')[1]}) AND category_id = $cat AND merchant_key != $m "
          "AND gmv_per_day BETWEEN $g/4 AND $g*4"),
         "هم‌صنف، با فروش روزانه در محدوده ¼ تا ۴ برابر شما"),
        ("category",
         f"({POOL_SQL.split('WHERE')[1]}) AND category_id = $cat AND merchant_key != $m",
         "همه پذیرندگان فعال هم‌صنف شما (دست‌کم ۵۰۰ جلسه)"),
    ]
    params = {"m": m, "cat": me["category_id"], "g": me["gmv_per_day"] or 0, "tk": me["median_ticket"] or 0}
    chosen = None
    for level, where, rule_fa in levels:
        used = {k: v for k, v in params.items() if f"${k}" in where}
        rows = q(f"SELECT merchant_key FROM merchant_stats WHERE {where}", used)
        if len(rows) >= PREFERRED_PEERS:
            chosen = (level, where, rule_fa, rows)
            break
        if chosen is None or len(rows) > len(chosen[3]):
            chosen = (level, where, rule_fa, rows)
    level, where, rule_fa, rows = chosen
    keys = [r["merchant_key"] for r in rows]
    return {"peers": keys, "n": len(keys), "rule_fa": rule_fa, "level": level, "me": me,
            "sufficient": len(keys) >= MIN_PEERS,
            "where_sql": where, "params": {k: v for k, v in params.items() if k != "m"}}


def peer_period_rates(peer_keys: list[str], f: str, t: str) -> list[dict]:
    """Per-peer period-scoped rates from merchant_daily (same period as the merchant's)."""
    if not peer_keys:
        return []
    exprs = ", ".join(f"{sql} AS {k}" for k, (sql, _) in BENCH_METRICS.items())
    return q(f"""
        SELECT merchant_key, sum(sessions) AS sessions, {exprs}
        FROM merchant_daily
        WHERE merchant_key IN (SELECT unnest($keys::varchar[])) AND d BETWEEN $f AND $t
        GROUP BY merchant_key HAVING sum(sessions) >= 100""",
        {"keys": peer_keys, "f": f, "t": t})


def _quantile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = p * (len(sorted_vals) - 1)
    lo, hi = int(idx), min(int(idx) + 1, len(sorted_vals) - 1)
    frac = idx - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def benchmarks(m: str, f: str, t: str) -> dict:
    from .analytics import period_agg
    g = peer_group(m)
    me = period_agg(m, f, t)
    fp = me["attempted"] - me["first_try_ok"] - 0  # first-fail pool incl. later-success
    me_vals = {
        "conv": me["conv"], "first_try_conv": me["first_try_conv"],
        "no_attempt_rate": me["no_attempt_rate"], "inbank_abandon_rate": me["inbank_abandon_rate"],
        "recovery_rate": (me["recovered"] / fp) if fp > 0 else None,
    }
    rows, suppressed = [], not g.get("sufficient")
    peers = peer_period_rates(g["peers"], f, t) if not suppressed else []
    if len(peers) < MIN_PEERS:
        suppressed = True
    for key, (_, higher_better) in BENCH_METRICS.items():
        mine = me_vals.get(key)
        if suppressed or mine is None:
            rows.append({"metric": key, "value": mine, "suppressed": True})
            continue
        vals = sorted(v[key] for v in peers if v[key] is not None)
        if len(vals) < MIN_PEERS:
            rows.append({"metric": key, "value": mine, "suppressed": True})
            continue
        better = sum(1 for v in vals if (mine > v) == higher_better and mine != v)
        pct = round(100 * better / len(vals))
        rows.append({
            "metric": key, "value": mine, "suppressed": False,
            "p25": _quantile(vals, 0.25), "p50": _quantile(vals, 0.5), "p75": _quantile(vals, 0.75),
            "percentile": pct, "n_peers": len(vals), "higher_better": higher_better,
            # with a small pool the percentile is coarse and noisy — the UI shows a caution
            # and quotes rank ("better than k of n") rather than a precise percentile.
            "low_n": len(vals) < 8,
        })
    return {
        "group": {"n": g["n"], "rule_fa": g["rule_fa"], "level": g["level"],
                  "sufficient": not suppressed,
                  "me": {k: g["me"].get(k) for k in ("category_title", "gmv_per_day", "median_ticket", "sessions")}},
        "rows": rows,
        "evidence": evidence("peer_percentile",
                             sql=f"SELECT merchant_key FROM merchant_stats WHERE {g.get('where_sql','')}",
                             params=g.get("params", {}), n=g["n"], period=_p(f, t),
                             extra={"rule_fa": g["rule_fa"],
                                    "note_fa": "صدک با رتبه دقیق در میان همتایان محاسبه می‌شود، نه با فرض توزیع."}),
    }


def _p(f: str, t: str) -> str:
    return f"{f} تا {t}"
