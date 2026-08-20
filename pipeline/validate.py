# Independent analytical QA: recompute headline numbers straight from the RAW CSV
# (bypassing marts and the app code path) and compare with the live API.
# Run with the server up: uv run python pipeline/validate.py
import json
import os
import urllib.request

import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV = os.environ.get("ZARIN_DATA_PATH", os.path.join(ROOT, "data", "other_challenge_data.csv.gz"))
API = "http://localhost:8630/api"
MERCHANTS = ["M156", "M43", "M265"]
F, T = "2026-01-01", "2026-06-30"

con = duckdb.connect()
con.execute(f"CREATE VIEW raw AS SELECT * FROM read_csv_auto('{CSV}', header=true, sample_size=200000)")


def api(path, **params):
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    with urllib.request.urlopen(f"{API}/{path}?{qs}") as r:
        return json.loads(r.read())


def raw_truth(m):
    # session-level ground truth, written independently of zarin/pipeline.py
    row = con.execute("""
        WITH s AS (
          SELECT session_key,
                 any_value(session_status) ss,
                 any_value(amount) amount,
                 max(CASE WHEN try_seq>0 THEN 1 ELSE 0 END) attempted,
                 count(DISTINCT CASE WHEN try_seq>0 THEN try_seq END) n_tries,
                 min(CASE WHEN try_seq>0 THEN try_seq END) first_seq
          FROM raw WHERE merchant_key = ? GROUP BY session_key),
        f AS (SELECT r.session_key, r.try_status fstat
              FROM raw r JOIN s ON r.session_key=s.session_key AND r.try_seq=s.first_seq)
        SELECT count(*) sessions,
               sum((s.ss='Verified')::int) verified,
               sum(CASE WHEN s.ss='Verified' THEN s.amount ELSE 0 END) gmv,
               sum((s.attempted=0)::int) no_attempt,
               sum((s.ss='Paid')::int) paid_unverified,
               sum(CASE WHEN s.ss='Paid' THEN s.amount ELSE 0 END) paid_amount,
               sum((s.ss IN ('Verified','Paid') AND s.n_tries>1
                    AND f.fstat NOT IN ('Verified','Paid'))::int) recovered,
               sum((f.fstat='Verified')::int) first_try_verified
        FROM s LEFT JOIN f ON s.session_key=f.session_key
    """, [m]).fetchone()
    keys = ["sessions", "verified", "gmv", "no_attempt", "paid_unverified", "paid_amount",
            "recovered", "first_try_verified"]
    return dict(zip(keys, [int(x or 0) for x in row]))


fails = 0
for m in MERCHANTS:
    truth = raw_truth(m)
    ov = api("overview", m=m, f=F, t=T)["kpis"]
    fu = api("funnel", m=m, f=F, t=T)
    checks = [
        ("sessions", truth["sessions"], ov["sessions"]),
        ("verified", truth["verified"], ov["verified"]),
        ("gmv", truth["gmv"], ov["gmv"]),
        ("no_attempt", truth["no_attempt"], fu["outcomes"]["no_attempt"]),
        ("paid_unverified", truth["paid_unverified"], ov["paid_unverified"]),
        ("paid_amount", truth["paid_amount"], ov["paid_unverified_amount"]),
        ("recovered", truth["recovered"], fu["recovery"]["recovered"]),
        ("first_try_verified/sessions", round(truth["first_try_verified"] / truth["sessions"], 6),
         round(fu["rates"]["first_try_conv"], 6)),
    ]
    for name, expect, got in checks:
        ok = abs(float(expect) - float(got)) < 1e-6
        fails += 0 if ok else 1
        print(f"{m:6} {name:28} raw={expect:>18} api={got:>18} {'OK' if ok else '** MISMATCH **'}")

print("RESULT:", "ALL CHECKS PASSED" if fails == 0 else f"{fails} MISMATCHES")
raise SystemExit(1 if fails else 0)
