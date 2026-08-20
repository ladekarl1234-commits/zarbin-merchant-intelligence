# Audit pass 2: semantic disambiguation. Run: uv run python pipeline/audit2.py
import duckdb, json, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV = os.environ.get("ZARIN_DATA_PATH", os.path.join(ROOT, "data", "other_challenge_data.csv.gz"))
con = duckdb.connect()
con.execute(f"CREATE VIEW raw AS SELECT * FROM read_csv_auto('{CSV}', header=true, sample_size=200000)")

R = {}
def q(name, sql):
    r = con.execute(sql).fetchall()
    cols = [d[0] for d in con.description]
    R[name] = [dict(zip(cols, row)) for row in r]

# 1. sessions mixing seq0 and seq>0
q("mixed_seq0", "SELECT count(*) n FROM (SELECT session_key FROM raw GROUP BY 1 HAVING sum((try_seq=0)::int)>0 AND sum((try_seq>0)::int)>0)")
# 2. negative try delay distribution
q("try_delay", """SELECT quantile_cont(d,0.01) p1, quantile_cont(d,0.1) p10, quantile_cont(d,0.5) p50, quantile_cont(d,0.9) p90, min(d) mn
 FROM (SELECT epoch(try_created_at - created_at) d FROM raw WHERE try_created_at IS NOT NULL)""")
# 3. settled vs verified deltas
q("settle_verify", """SELECT count(*) n, sum((settled_at IS NOT NULL AND verified_at IS NULL)::int) settled_only,
 sum((verified_at IS NOT NULL AND settled_at IS NULL)::int) verified_only,
 quantile_cont(epoch(verified_at - settled_at),0.5) med_v_minus_s_sec,
 quantile_cont(epoch(verified_at - settled_at),0.95) p95_v_minus_s_sec
 FROM raw WHERE try_status IN ('Verified','Paid')""")
q("settled_by_try_status", "SELECT try_status, sum((settled_at IS NOT NULL)::int) has_settled, sum((verified_at IS NOT NULL)::int) has_verified, count(*) n FROM raw GROUP BY 1")
# 4. Paid-not-verified: value and spread
q("paid_value", """SELECT count(DISTINCT merchant_key) merchants, count(*) sessions, sum(amount) total_amount,
 sum((verify_type='Manual')::int) manual_rows FROM raw WHERE session_status='Paid' AND try_status='Paid'""")
q("paid_top_merchants", "SELECT merchant_key, count(*) n, sum(amount) amt FROM raw WHERE session_status='Paid' AND try_status='Paid' GROUP BY 1 ORDER BY amt DESC LIMIT 8")
q("paid_monthly", "SELECT date_trunc('month', created_at) m, count(*) n FROM raw WHERE session_status='Paid' AND try_status='Paid' GROUP BY 1 ORDER BY 1")
# 5. TTL
q("ttl", "SELECT round(epoch(expire_in - created_at)/60) ttl_min, count(*) n FROM raw GROUP BY 1 ORDER BY n DESC LIMIT 6")
# 6. repeat share by category (verified sessions only, card known)
q("repeat_by_cat", """WITH v AS (SELECT category_title, merchant_key, payer_card_key, session_key, amount FROM raw WHERE try_status='Verified'),
 c AS (SELECT category_title, merchant_key, payer_card_key, count(*) k FROM v GROUP BY 1,2,3)
 SELECT v.category_title, count(DISTINCT v.merchant_key||v.payer_card_key) customers,
  sum((c.k>1)::int)/count(*) repeat_txn_share,
  count(DISTINCT CASE WHEN c.k>1 THEN v.merchant_key||v.payer_card_key END)/count(DISTINCT v.merchant_key||v.payer_card_key) repeat_cust_share
 FROM v JOIN c USING (category_title, merchant_key, payer_card_key) GROUP BY 1""")
# 7. amount band conversion (session level)
q("amount_conv", """WITH s AS (SELECT session_key, max(amount) amount, max(session_status) st, max((try_seq>0)::int) attempted FROM raw GROUP BY 1)
 SELECT CASE WHEN amount<200000 THEN 'a<200K' WHEN amount<1000000 THEN 'b200K-1M' WHEN amount<5000000 THEN 'c1M-5M'
   WHEN amount<20000000 THEN 'd5M-20M' WHEN amount<100000000 THEN 'e20M-100M' ELSE 'f>100M' END band,
  count(*) sessions, avg((st='Verified')::int) conv, avg(attempted) attempt_rate
 FROM s GROUP BY 1 ORDER BY 1""")
# 8. retry delay between try1 and try2
q("retry_gap", """SELECT quantile_cont(gap,0.5) med_sec, quantile_cont(gap,0.9) p90_sec FROM (
 SELECT epoch(t2.try_created_at - t1.try_created_at) gap FROM raw t1 JOIN raw t2
 ON t1.session_key=t2.session_key AND t1.try_seq=1 AND t2.try_seq=2)""")
# 9. failed session last-try composition
q("failed_last_stage", """WITH s AS (SELECT session_key, max(try_seq) last_seq FROM raw WHERE session_status='Failed' GROUP BY 1)
 SELECT r.try_status, count(*) sessions FROM raw r JOIN s ON r.session_key=s.session_key AND r.try_seq=s.last_seq GROUP BY 1 ORDER BY 2 DESC""")
# 10. conversion by category
q("cat_conv", """WITH s AS (SELECT session_key, max(category_title) cat, max(session_status) st, max((try_seq>0)::int) att FROM raw GROUP BY 1)
 SELECT cat, count(*) sessions, avg((st='Verified')::int) conv, 1-avg(att) noattempt_rate FROM s GROUP BY 1 ORDER BY 2 DESC""")
# 11. merchant summary for demo selection: top by GMV + flags
q("merchant_summary", """WITH s AS (SELECT session_key, max(merchant_key) mk, max(category_title) cat, max(amount) amount, max(session_status) st,
   max((try_seq>0)::int) att, count(*) tries FROM raw GROUP BY 1),
 m AS (SELECT mk, cat, count(*) sessions, sum((st='Verified')::int) verified, sum(CASE WHEN st='Verified' THEN amount END) gmv,
   avg((st='Verified')::int) conv, 1-avg(att) noatt, sum((st='Paid')::int) paid_stuck,
   sum(CASE WHEN st='Verified' AND tries>1 THEN 1 ELSE 0 END) multi_try_wins
  FROM s GROUP BY 1,2)
 SELECT * FROM m WHERE sessions>5000 ORDER BY gmv DESC NULLS LAST LIMIT 20""")
# 12. weekday conversion
q("weekday", """WITH s AS (SELECT session_key, min(created_at) t, max(session_status) st FROM raw GROUP BY 1)
 SELECT dayofweek(t) dow, count(*) sessions, avg((st='Verified')::int) conv FROM s GROUP BY 1 ORDER BY 1""")
# 13. PSP within-merchant success spread (only merchants using >=2 PSPs, attempts)
q("psp_within_merchant", """WITH a AS (SELECT merchant_key, psp_code, count(*) n, avg((try_status IN ('Verified','Paid'))::int) ok
  FROM raw WHERE try_seq>0 GROUP BY 1,2 HAVING n>=200)
 SELECT psp_code, count(*) merchant_pairs, quantile_cont(ok,0.5) med_ok FROM a GROUP BY 1 ORDER BY 3""")
# 14. bank success on real attempts (bank known only post-attempt? verify)
q("bank_known_stage", "SELECT try_status, sum((issuer_bank_code IS NOT NULL)::int) has_bank, count(*) n FROM raw WHERE try_seq>0 GROUP BY 1")
# 15. Verified sessions where verified try is not last try
q("verify_time_within", "SELECT quantile_cont(epoch(verified_at - created_at),0.5) med_sec_create_to_verify FROM raw WHERE try_status='Verified'")

print(json.dumps(R, ensure_ascii=False, default=str))
