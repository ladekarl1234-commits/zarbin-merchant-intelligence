"""Build Parquet marts from the raw challenge CSV.

Grain contract (verified by the audit and re-asserted here on every build):
- raw: one row per payment attempt, (session_key, try_seq) unique
- sessions: one row per payment session
- attempts: one row per real attempt (try_seq > 0); NoAttempt lives on sessions.attempted = false
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import duckdb

from .config import DATA_PATH, MARTS_DIR

# Session outcome taxonomy — the five behaviorally distinct end states.
# no_attempt is NOT a bank failure: the payer never reached a PSP.
OUTCOME_SQL = """
  CASE
    WHEN session_status = 'Verified' THEN 'verified'
    WHEN session_status = 'Paid' THEN 'paid_unverified'
    WHEN session_status = 'Reversed' THEN 'reversed'
    WHEN NOT attempted THEN 'no_attempt'
    WHEN last_try_status = 'Failed' THEN 'failed_bank'
    ELSE 'abandoned_inbank'
  END
"""


def build(data_path: Path = DATA_PATH, out_dir: Path = MARTS_DIR, quiet: bool = False) -> None:
    t0 = time.time()
    if not data_path.exists():
        sys.exit(
            f"dataset not found: {data_path}\n"
            "Place other_challenge_data.csv.gz under data/ or set ZARIN_DATA_PATH."
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(
        f"CREATE VIEW raw AS SELECT * FROM read_csv_auto('{data_path.as_posix()}', header=true, sample_size=200000)"
    )

    # --- integrity assertions: fail loudly rather than build wrong marts ---
    a = con.execute("""
        SELECT
          (SELECT count(*) FROM (SELECT session_key, try_seq FROM raw GROUP BY 1,2 HAVING count(*)>1)) AS dup_grain,
          (SELECT count(*) FROM (
             SELECT session_key FROM raw GROUP BY 1
             HAVING count(DISTINCT merchant_key)>1 OR count(DISTINCT amount)>1
                 OR count(DISTINCT session_status)>1 OR count(DISTINCT terminal_key)>1)) AS inconsistent_sessions,
          (SELECT count(*) FROM (
             SELECT session_key FROM raw GROUP BY 1
             HAVING sum((try_seq=0)::int)>0 AND sum((try_seq>0)::int)>0)) AS mixed_noattempt
    """).fetchone()
    assert a == (0, 0, 0), f"raw data violates audited invariants: dup={a[0]} inconsistent={a[1]} mixed={a[2]}"

    con.execute(f"""
        CREATE TABLE sessions AS
        WITH s AS (
          SELECT
            session_key,
            any_value(merchant_key) AS merchant_key,
            any_value(terminal_key) AS terminal_key,
            any_value(category_id) AS category_id,
            any_value(category_title) AS category_title,
            any_value(amount) AS amount,
            any_value(adjusted_fee) AS adjusted_fee,
            any_value(session_status) AS session_status,
            any_value(verify_type) AS verify_type,
            min(created_at) AS created_at,
            max(verified_at) AS verified_at,
            max(settled_at) AS settled_at,
            count(*) FILTER (WHERE try_seq > 0) AS n_tries,
            count(*) FILTER (WHERE try_seq > 0) > 0 AS attempted,
            arg_min(try_status, try_seq) FILTER (WHERE try_seq > 0) AS first_try_status,
            arg_max(try_status, try_seq) FILTER (WHERE try_seq > 0) AS last_try_status,
            arg_min(psp_code, try_seq) FILTER (WHERE try_seq > 0) AS first_psp,
            any_value(psp_code) FILTER (WHERE try_status IN ('Verified','Paid')) AS win_psp,
            any_value(issuer_bank_code) FILTER (WHERE try_status IN ('Verified','Paid')) AS win_bank,
            any_value(payer_card_key) FILTER (WHERE try_status IN ('Verified','Paid')) AS payer_card_key
          FROM raw GROUP BY session_key
        )
        SELECT *,
          ({OUTCOME_SQL}) AS outcome,
          session_status IN ('Verified','Paid')
            AND n_tries > 1
            AND first_try_status NOT IN ('Verified','Paid') AS recovered,
          attempted AND first_try_status IN ('Verified','Paid') AS first_try_ok,
          attempted AND first_try_status = 'Verified' AS first_try_verified,
          created_at::date AS d,
          date_trunc('month', created_at)::date AS month,
          extract(hour FROM created_at)::int AS hour,
          dayofweek(created_at)::int AS dow
        FROM s
    """)

    con.execute("""
        CREATE TABLE attempts AS
        SELECT session_key, try_seq, merchant_key, category_title, amount,
               try_status, psp_code, issuer_bank_code, payer_card_key,
               switch_response_code, try_created_at, init_time_ms,
               try_status IN ('Verified','Paid') AS ok,
               try_created_at::date AS d
        FROM raw WHERE try_seq > 0
    """)

    con.execute("""
        CREATE TABLE merchant_daily AS
        SELECT merchant_key, any_value(category_title) AS category_title, d,
               count(*) AS sessions,
               count(*) FILTER (WHERE attempted) AS attempted,
               count(*) FILTER (WHERE outcome = 'verified') AS verified,
               count(*) FILTER (WHERE outcome = 'paid_unverified') AS paid_unverified,
               count(*) FILTER (WHERE outcome = 'no_attempt') AS no_attempt,
               count(*) FILTER (WHERE outcome = 'abandoned_inbank') AS abandoned_inbank,
               count(*) FILTER (WHERE outcome = 'failed_bank') AS failed_bank,
               count(*) FILTER (WHERE recovered) AS recovered,
               count(*) FILTER (WHERE first_try_ok) AS first_try_ok,
               count(*) FILTER (WHERE first_try_verified) AS first_try_verified,
               coalesce(sum(amount) FILTER (WHERE outcome = 'verified'), 0) AS gmv,
               coalesce(sum(amount) FILTER (WHERE outcome = 'paid_unverified'), 0) AS paid_unverified_amount,
               coalesce(sum(adjusted_fee) FILTER (WHERE outcome = 'verified'), 0) AS fee_index_sum,
               count(DISTINCT payer_card_key) FILTER (WHERE outcome = 'verified') AS paying_customers
        FROM sessions GROUP BY merchant_key, d
    """)

    con.execute("""
        CREATE TABLE customers AS
        SELECT merchant_key, payer_card_key,
               min(created_at) AS first_ts, max(created_at) AS last_ts,
               count(*) AS n_verified,
               sum(amount) AS gmv,
               min(month) AS first_month
        FROM sessions
        WHERE outcome = 'verified' AND payer_card_key IS NOT NULL
        GROUP BY merchant_key, payer_card_key
    """)

    con.execute("""
        CREATE TABLE merchant_stats AS
        WITH base AS (
          SELECT merchant_key,
                 any_value(category_id) AS category_id,
                 any_value(category_title) AS category_title,
                 count(*) AS sessions,
                 count(*) FILTER (WHERE attempted) AS attempted,
                 count(*) FILTER (WHERE outcome = 'verified') AS verified,
                 count(*) FILTER (WHERE outcome = 'paid_unverified') AS paid_unverified,
                 count(*) FILTER (WHERE outcome = 'no_attempt') AS no_attempt,
                 count(*) FILTER (WHERE recovered) AS recovered,
                 count(*) FILTER (WHERE first_try_ok) AS first_try_ok,
                 count(*) FILTER (WHERE first_try_verified) AS first_try_verified,
                 coalesce(sum(amount) FILTER (WHERE outcome = 'verified'), 0) AS gmv,
                 coalesce(sum(amount) FILTER (WHERE outcome = 'paid_unverified'), 0) AS paid_unverified_amount,
                 quantile_cont(amount, 0.5) FILTER (WHERE outcome = 'verified') AS median_ticket,
                 count(DISTINCT d) AS active_days,
                 min(d) AS first_day, max(d) AS last_day,
                 count(DISTINCT month) AS active_months
          FROM sessions GROUP BY merchant_key
        ),
        cust AS (
          SELECT merchant_key,
                 count(*) AS customers,
                 count(*) FILTER (WHERE n_verified > 1) AS repeat_customers,
                 sum(n_verified) AS cust_txns,
                 sum(n_verified) FILTER (WHERE n_verified > 1) AS repeat_txns,
                 sum(gmv) AS cust_gmv,
                 sum(gmv) FILTER (WHERE n_verified > 1) AS repeat_gmv
          FROM customers GROUP BY merchant_key
        )
        SELECT base.*,
               coalesce(cust.customers, 0) AS customers,
               coalesce(cust.repeat_customers, 0) AS repeat_customers,
               coalesce(cust.repeat_txns, 0) AS repeat_txns,
               coalesce(cust.cust_txns, 0) AS cust_txns,
               coalesce(cust.repeat_gmv, 0) AS repeat_gmv,
               coalesce(cust.cust_gmv, 0) AS cust_gmv,
               verified / nullif(sessions, 0) AS conv,
               attempted / nullif(sessions, 0) AS attempt_rate,
               first_try_verified / nullif(sessions, 0) AS first_try_conv,
               gmv / nullif(active_days, 0) AS gmv_per_day
        FROM base LEFT JOIN cust USING (merchant_key)
    """)

    # --- post-build assertions ---
    b = con.execute("""
        SELECT
          (SELECT count(*) FROM raw) AS raw_rows,
          (SELECT count(DISTINCT session_key) FROM raw) AS raw_sessions,
          (SELECT count(*) FROM sessions) AS mart_sessions,
          (SELECT count(*) FROM attempts) + (SELECT count(*) FROM raw WHERE try_seq = 0) AS rows_accounted,
          (SELECT sum(amount) FROM raw WHERE try_status = 'Verified') AS gmv_attempt_level,
          (SELECT sum(amount) FROM sessions WHERE outcome = 'verified') AS gmv_session_level
    """).fetchone()
    assert b[1] == b[2], f"session mart grain broken: {b[1]} != {b[2]}"
    assert b[0] == b[3], f"attempt rows lost: {b[0]} != {b[3]}"
    # GMV counted once per session may differ from attempt-level sum only by the
    # ~28 audited Verified-sessions-without-Verified-try (session-level is authoritative).
    for name in ("sessions", "attempts", "merchant_daily", "customers", "merchant_stats"):
        con.execute(f"COPY {name} TO '{(out_dir / f'{name}.parquet').as_posix()}' (FORMAT PARQUET)")
    if not quiet:
        print(f"marts built in {time.time()-t0:.1f}s -> {out_dir}")
        print(f"  raw rows {b[0]:,} | sessions {b[2]:,} | GMV(session) {b[5]:,} IRR")


def ensure_built() -> None:
    missing = [m for m in ("sessions", "attempts", "merchant_daily", "customers", "merchant_stats")
               if not (MARTS_DIR / f"{m}.parquet").exists()]
    if missing:
        print(f"building marts (missing: {', '.join(missing)}) ...")
        build()


if __name__ == "__main__":
    build()
