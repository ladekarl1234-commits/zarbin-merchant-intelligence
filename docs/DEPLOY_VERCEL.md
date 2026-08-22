# Deploying Zarbin to Vercel

Live: **https://zarbin-nine.vercel.app**

The interesting part is not the deploy command. It is that a 2.2-million-row analytical
product with no database server runs inside a serverless function, answers from the CDN,
and stays byte-identical to what `uv run zarin` serves locally.

---

## 1. The shape

```
public/                    static SPA  → Vercel CDN, never touches the function
app.py                     `from zarin.api import app` — the Python entrypoint Vercel detects
zarin/                     the same package that runs locally, unmodified
data/marts/*.parquet       63 MB, shipped INSIDE the function bundle
requirements.txt           duckdb + fastapi. Nothing else.
vercel.json                region, maxDuration, excludeFiles, security headers
.vercelignore              what NOT to upload — see §3
```

There is no Vercel-specific fork of the request path. `app.py` is two lines; every route,
guard, cache and query is the code the local server runs.

---

## 2. Four constraints, and what each one forced

### 2.1 The dataset has to be *in* the bundle

Vercel's Python runtime bundles the whole project directory (no tree-shaking) with a 250 MB
uncompressed limit. There is no database to point at, and reading parquet over HTTP on every
cold start would trade a size problem for a latency one.

So the marts ship with the code. To make them fit, `zarin/pipeline.py` writes **ZSTD level 15**
instead of Snappy, sorted by `merchant_key, d, <unique key>`:

| mart | Snappy | ZSTD-15 |
|---|---|---|
| sessions (2.06M rows) | 55.6 MB | **36.7 MB** |
| attempts (1.95M rows) | 34.7 MB | **22.4 MB** |
| customers (396k rows) | 9.8 MB | **6.5 MB** |
| merchant_daily + merchant_stats | 0.35 MB | 0.25 MB |
| **total** | **100 MB** | **63 MB** |

This is **lossless** and was verified as such, not assumed: every one of 56 API responses was
captured before and after the change and compared field-by-field after masking the volatile
timestamps. Zero analytical differences. The re-sort also gave a free 2× speed-up locally
(warm p50 40 ms → 22 ms) because per-merchant queries prune more row groups.

The sort key ends in the mart's **unique** key so a rebuild is byte-reproducible — without a
tiebreaker DuckDB's parallel sort orders tied rows differently between runs, which changes
the file hash and the row order any un-`ORDER`ed query returns.

Final bundle: 63 MB of data + duckdb + fastapi, comfortably inside the limit.

### 2.2 `.gitignore` would have deleted the data

Vercel falls back to `.gitignore` when there is no `.vercelignore` — and `data/` is
git-ignored, because the dataset is not committed. The first deploy would have shipped a
function with no parquet and 500'd on every request.

`.vercelignore` therefore replaces that fallback explicitly: marts **in**, and the 59 MB
source CSV, `frontend/`, `node_modules`, `tests/`, `docs/`, screenshots and the venv **out**.
`vercel.json`'s `excludeFiles` repeats the exclusions as belt-and-braces, because the two
mechanisms run at different stages (upload vs. bundle).

### 2.3 A serverless filesystem is read-only

Telemetry writes JSONL. `ZARIN_TELEMETRY_DIR=/tmp/zarbin-telemetry` points it at the one
writable path. `store.EventLog` already swallows `OSError` on write — telemetry must never
break the request path — so this is belt-and-braces too, but an unwritable path would have
silently zeroed the AI-Ops surface.

Consequence, stated honestly: telemetry is **per-instance and non-durable**. Product
Performance and AI Operations show what *this* warm instance has seen. That is the
documented hackathon store, not a production observability stack (ADR-0001).

### 2.4 The operator surface must not be open to the internet

`_admin_guard` used to answer a non-loopback deployment with a flat `503` — fail-closed, but
it took the whole Control Center off the air rather than gating it. It now requires a
**signed, expiring ops-scope session token** whenever `ZARIN_ADMIN_TOKEN` is unset and the
host is not loopback. The ops login mints one; `/api/admin/*` returns `403 ops session
required` without it.

Verified live:

```
$ curl -s https://zarbin-nine.vercel.app/api/admin/platform
{"detail":"ops session required"}      # 403
```

**This is a demo gate, not identity.** `POST /api/auth/session?scope=ops` is unauthenticated,
so anyone who reads this document can mint a token. What it buys is that the operator surface
is not answering anonymous GETs, and that the session is signed and expires (12h default).
Real auth is an OIDC/RBAC migration, designed in `DEPLOYMENT_SPEC.md` and deliberately not
built for a single-tenant demo over an anonymised dataset.

---

## 3. Latency

Three layers, each doing a different job.

**CDN.** The marts are immutable for the life of a deployment, so every read endpoint is a
pure function of its path and query. `zarin/cache.py` sets
`Cache-Control: public, max-age=60, s-maxage=31536000, stale-while-revalidate=86400` on nine
deterministic GET routes. A redeploy publishes new marts *and* a new CDN namespace at the
same instant, so there is no window in which a stale body can be served.

Not cached, deliberately: `/api/copilot` (emits one AI-telemetry event per call, which the
Control Center reports — a cache would silently stop that signal) and `/api/admin/*` (the
operator gate runs in the route's dependencies, i.e. *after* middleware; caching there would
answer before the guard).

**Process.** A bounded LRU of already-serialised bodies, keyed identically, for a cold edge
or a query the CDN has not seen. Plus `lru_cache` on the three heavy Control Center
aggregations and on the copilot's plan.

**Region.** The function runs in `fra1`, next to the edge PoP serving the region, instead of
the default `iad1` — that alone removed a ~180 ms transatlantic hop per uncached request.

Measured on the live deployment, 71 endpoint cases × 3 rounds, using the `Server-Timing`
header the app sets on every response (so client RTT is excluded):

| group | n | server p50 | server p95 | CDN |
|---|---|---|---|---|
| data endpoints | 23 | 84 ms | 538 ms | **HIT 23/23** |
| copilot (deterministic) | 36 | 6 ms | 102 ms | MISS (by design) |
| Control Center | 9 | 4 ms | 6 ms | BYPASS (by design) |
| **everything except the LLM pass** | **68** | **19 ms** | **325 ms** | |
| `/api/copilot/polish` (LLM) | 3 | 2.8 s | 17 s | off the answer path |

Non-2xx across the whole probe: **0**.

---

## 4. The LLM is not on the answer path

Free models are what the free-model policy (ADR-0003) commits this product to, and they were
measured rather than assumed. Five real deterministic answers, rephrased, then judged by
Zarbin's own grounding guard:

| model | grounded | avg | note |
|---|---|---|---|
| `nvidia/nemotron-3-super-120b-a12b:free` | **4/5** | 3.2 s | the default |
| `nvidia/nemotron-3-nano-30b-a3b:free` | 0/5 | 1.7 s | flips negations |
| `cohere/north-mini-code:free` | 0/5 | 10.9 s | |
| `google/gemma-4-31b-it:free` | — | — | HTTP 429 on every call |
| `z-ai/glm-5.2:free` | — | — | HTTP 429 on every call |

The previous default, `deepseek/deepseek-chat-v3-0324:free`, **no longer exists** on the free
tier — every call 404s and falls back. A dead default is worse than no default precisely
because the fallback hides it.

So: putting 3.2 s (5.1 s p95) in front of an answer the engine already has in ~40 ms, and
discarding one rephrasing in five, would make every question slower and one in five no
better. `/api/copilot` is deterministic, always. `/api/copilot/polish` offers the same answer
rephrased, and the client calls it *after* rendering — if it is slow, rate-limited,
ungrounded or the key is absent, the merchant simply keeps the answer they already have.

Cost on the live deployment: **$0.00**. The policy is enforced at construction *and* per
request; a non-`:free` id is normalised back to the default rather than silently used.

---

## 5. Reproducing the deploy

```bash
# 1. build the marts (writes ZSTD parquet into data/marts/)
uv run python -m zarin.pipeline

# 2. build the SPA and sync it to the static dir Vercel serves from the CDN
cd frontend && npm ci && npm run build && cd ..
rm -rf public && mkdir public && cp -r zarin/static/* public/

# 3. link and configure
vercel link
printf '0.0.0.0'                | vercel env add ZARIN_HOST production
printf '/tmp/zarbin-telemetry'  | vercel env add ZARIN_TELEMETRY_DIR production
python -c "import secrets;print(secrets.token_urlsafe(32))" \
                                | vercel env add ZARIN_SESSION_SECRET production
printf '<openrouter key>'       | vercel env add OPENROUTER_API_KEY production      # optional
printf 'nvidia/nemotron-3-super-120b-a12b:free' | vercel env add OPENROUTER_MODEL production
printf '12'                     | vercel env add OPENROUTER_TIMEOUT production

# 4. ship
vercel deploy --prod
```

`ZARIN_SESSION_SECRET` must be set: without it `auth.py` generates a random secret per
process, so a token minted by one warm instance is rejected by the next — invisible locally,
a random logout in production.

Notes on things that will bite:

- `memory` in `vercel.json` is **ignored** on Active CPU billing (and capped at 2048 MB on
  Hobby regardless). It is not in the committed config.
- The build log should say *"Installing required dependencies from pyproject.toml"* or
  *requirements.txt*. If it installs the `dev` group, pytest and ruff land in the bundle.
- `git`-connecting the project would trigger deploys that ship **no marts**. This project
  deploys from the CLI on purpose.

---

## 6. Verifying a deploy

```bash
# every endpoint, 3 rounds, with server-side timing and CDN hit/miss
uv run python pipeline/_bench/probe.py https://zarbin-nine.vercel.app out.json --rounds 3
```

The probe asserts nothing on its own — read the summary. What should be true:

- `NON-2xx: 0`
- every `/api/{meta,overview,insights,funnel,customers,peers,changes,quality,evidence/*}`
  reports `X-Vercel-Cache: HIT` on the second round
- `/api/admin/*` without an ops token is `403`, and `200` with one
- `/api/nope` is a **JSON 404**, not the SPA shell with HTTP 200
- `Server-Timing: app;dur=…` present on every `/api/*` response
