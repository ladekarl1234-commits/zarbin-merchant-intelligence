# Critical data audit for the ZarinPal challenge dataset.
# Run: uv run python pipeline/audit.py
# Emits docs/data_audit_raw.json and prints a compact summary.
import duckdb, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV = os.environ.get("ZARIN_DATA_PATH", os.path.join(ROOT, "data", "other_challenge_data.csv.gz"))
OUT = os.path.join(ROOT, "docs", "data_audit_raw.json")

con = duckdb.connect()
con.execute(f"CREATE VIEW raw AS SELECT * FROM read_csv_auto('{CSV}', header=true, sample_size=200000)")

R = {}
def q(name, sql):
    r = con.execute(sql).fetchall()
    cols = [d[0] for d in con.description]
    R[name] = [dict(zip(cols, row)) for row in r]
    return R[name]

q("shape", "SELECT count(*) n_rows, count(DISTINCT session_key) sessions, count(DISTINCT merchant_key) merchants, count(DISTINCT terminal_key) terminals, count(DISTINCT category_id) categories, min(created_at) t0, max(created_at) t1 FROM raw")
q("types", "DESCRIBE raw")
q("dup_grain", "SELECT count(*) dup_rows FROM (SELECT session_key, try_seq, count(*) c FROM raw GROUP BY 1,2 HAVING c>1)")
q("full_dup", "SELECT count(*) n FROM (SELECT *, count(*) OVER (PARTITION BY session_key, try_seq) c FROM raw) WHERE c>1")
q("missing", """SELECT
 sum((session_key IS NULL)::int) session_key, sum((try_seq IS NULL)::int) try_seq,
 sum((terminal_key IS NULL)::int) terminal_key, sum((merchant_key IS NULL)::int) merchant_key,
 sum((amount IS NULL)::int) amount, sum((adjusted_fee IS NULL)::int) adjusted_fee,
 sum((session_status IS NULL)::int) session_status, sum((try_status IS NULL)::int) try_status,
 sum((switch_response_code IS NULL)::int) switch_response_code, sum((psp_code IS NULL)::int) psp_code,
 sum((issuer_bank_code IS NULL)::int) issuer_bank_code, sum((payer_card_key IS NULL)::int) payer_card_key,
 sum((verify_type IS NULL)::int) verify_type, sum((init_time_ms IS NULL)::int) init_time_ms,
 sum((verify_time_ms IS NULL)::int) verify_time_ms, sum((created_at IS NULL)::int) created_at,
 sum((try_created_at IS NULL)::int) try_created_at, sum((verified_at IS NULL)::int) verified_at,
 sum((settled_at IS NULL)::int) settled_at, sum((expire_in IS NULL)::int) expire_in FROM raw""")
q("session_status_x_try_status", "SELECT session_status, try_status, count(*) n FROM raw GROUP BY 1,2 ORDER BY n DESC")
q("try_seq_dist", "SELECT try_seq, count(*) n FROM raw GROUP BY 1 ORDER BY 1 LIMIT 30")
q("noattempt", "SELECT try_status, sum((try_seq=0)::int) seq0, sum((try_seq>0)::int) seqpos, sum((try_created_at IS NULL)::int) no_try_ts, sum((psp_code IS NULL)::int) no_psp FROM raw GROUP BY 1")
q("session_consistency", """SELECT
 sum((n_status>1)::int) multi_session_status, sum((n_merchant>1)::int) multi_merchant,
 sum((n_terminal>1)::int) multi_terminal, sum((n_amount>1)::int) multi_amount,
 count(*) sessions
 FROM (SELECT session_key, count(DISTINCT session_status) n_status, count(DISTINCT merchant_key) n_merchant,
       count(DISTINCT terminal_key) n_terminal, count(DISTINCT amount) n_amount FROM raw GROUP BY 1)""")
q("session_status_dist", "SELECT session_status, count(DISTINCT session_key) sessions FROM raw GROUP BY 1 ORDER BY 2 DESC")
q("attempts_per_session", "SELECT n_tries, count(*) sessions FROM (SELECT session_key, count(*) n_tries FROM raw GROUP BY 1) GROUP BY 1 ORDER BY 1 LIMIT 20")
# retry recovery: sessions whose first real attempt failed but session eventually Verified/Paid
q("retry_recovery", """WITH s AS (
  SELECT session_key, max(session_status) ss, count(*) n,
    sum((try_status IN ('Verified','Paid'))::int) ok_tries,
    min(CASE WHEN try_seq>0 THEN try_seq END) first_real
  FROM raw GROUP BY 1),
 firstt AS (SELECT r.session_key, r.try_status fstat FROM raw r JOIN s ON r.session_key=s.session_key AND r.try_seq=s.first_real)
 SELECT s.ss session_status, (f.fstat IN ('Verified','Paid')) first_ok, count(*) sessions
 FROM s JOIN firstt f ON s.session_key=f.session_key GROUP BY 1,2 ORDER BY 3 DESC""")
q("paid_no_verified_at", "SELECT session_status, sum((verified_at IS NULL)::int) null_verified_at, count(*) n FROM raw WHERE try_status IN ('Paid','Verified') GROUP BY 1")
q("verified_session_wo_verified_try", """SELECT count(*) n FROM (
 SELECT session_key FROM raw GROUP BY 1
 HAVING max(session_status)='Verified' AND sum((try_status='Verified')::int)=0)""")
q("paid_session_wo_paid_or_verified_try", """SELECT count(*) n FROM (
 SELECT session_key FROM raw GROUP BY 1
 HAVING max(session_status)='Paid' AND sum((try_status IN ('Paid','Verified'))::int)=0)""")
q("verify_type", "SELECT verify_type, count(*) n FROM raw GROUP BY 1")
q("amount_pct", "SELECT min(amount) mn, quantile_cont(amount,0.25) p25, quantile_cont(amount,0.5) p50, quantile_cont(amount,0.75) p75, quantile_cont(amount,0.95) p95, quantile_cont(amount,0.99) p99, max(amount) mx, avg(amount) mean FROM raw")
q("fee_ratio", "SELECT quantile_cont(adjusted_fee/amount, 0.5) med_ratio, min(adjusted_fee/amount) mn, max(adjusted_fee/amount) mx, count(*) FILTER (adjusted_fee IS NULL) n_nulls FROM raw WHERE amount>0")
q("categories", "SELECT category_id, category_title, count(DISTINCT merchant_key) merchants, count(*) n FROM raw GROUP BY 1,2 ORDER BY n DESC")
q("terminal_merchant", "SELECT count(*) n_terminals, sum((m>1)::int) terminals_multi_merchant FROM (SELECT terminal_key, count(DISTINCT merchant_key) m FROM raw GROUP BY 1)")
q("merchant_multi_terminal", "SELECT sum((t>1)::int) merchants_multi_terminal, max(t) max_terminals FROM (SELECT merchant_key, count(DISTINCT terminal_key) t FROM raw GROUP BY 1)")
q("concentration", """WITH g AS (SELECT merchant_key, sum(amount) FILTER (try_status='Verified') gmv FROM raw GROUP BY 1)
 SELECT count(*) merchants, sum(gmv) total,
  sum(gmv) FILTER (rk<=5)/sum(gmv) top5_share, sum(gmv) FILTER (rk<=20)/sum(gmv) top20_share
 FROM (SELECT *, row_number() OVER (ORDER BY gmv DESC NULLS LAST) rk FROM g)""")
q("merchant_active_months", "SELECT n_months, count(*) merchants FROM (SELECT merchant_key, count(DISTINCT date_trunc('month', created_at)) n_months FROM raw GROUP BY 1) GROUP BY 1 ORDER BY 1")
q("monthly", "SELECT date_trunc('month', created_at) m, count(DISTINCT session_key) sessions, count(DISTINCT merchant_key) merchants, sum(amount) FILTER (try_status='Verified') gmv FROM raw GROUP BY 1 ORDER BY 1")
q("card_null_by_try_status", "SELECT try_status, sum((payer_card_key IS NULL)::int) card_null, count(*) n FROM raw GROUP BY 1")
q("card_cross_merchant", "SELECT count(*) cards, sum((m>1)::int) cards_multi_merchant FROM (SELECT payer_card_key, count(DISTINCT merchant_key) m FROM raw WHERE payer_card_key IS NOT NULL GROUP BY 1)")
q("psp", "SELECT psp_code, count(*) n, sum((try_status='Verified')::int) ok FROM raw GROUP BY 1 ORDER BY n DESC")
q("bank", "SELECT issuer_bank_code, count(*) n, sum((try_status='Verified')::int) ok FROM raw GROUP BY 1 ORDER BY n DESC LIMIT 12")
q("bank_card_count", "SELECT count(DISTINCT issuer_bank_code) banks FROM raw")
q("switch_codes", "SELECT switch_response_code, count(*) n FROM raw GROUP BY 1 ORDER BY n DESC LIMIT 15")
q("ts_sanity", """SELECT
 sum((try_created_at < created_at)::int) try_before_session,
 sum((verified_at < try_created_at)::int) verify_before_try,
 sum((settled_at < verified_at)::int) settle_before_verify,
 sum((expire_in < created_at)::int) expire_before_create,
 quantile_cont(epoch(expire_in - created_at)/60, 0.5) med_ttl_min
 FROM raw""")
q("timing", "SELECT quantile_cont(init_time_ms,0.5) init_p50, quantile_cont(init_time_ms,0.95) init_p95, quantile_cont(verify_time_ms,0.5) verify_p50, quantile_cont(verify_time_ms,0.95) verify_p95 FROM raw")
q("hourly_conv", "SELECT extract(hour FROM created_at) h, count(DISTINCT session_key) sessions, count(DISTINCT session_key) FILTER (session_status='Verified') ok FROM raw GROUP BY 1 ORDER BY 1")

def default(o):
    return str(o)
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(R, f, ensure_ascii=False, indent=1, default=default)
print(json.dumps(R, ensure_ascii=False, default=default))
