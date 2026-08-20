"""Central configuration: paths, thresholds, constants. One source of truth."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = Path(os.environ.get("ZARIN_DATA_PATH", ROOT / "data" / "other_challenge_data.csv.gz"))
MARTS_DIR = Path(os.environ.get("ZARIN_MARTS_DIR", ROOT / "data" / "marts"))
STATIC_DIR = ROOT / "zarin" / "static"

PORT = int(os.environ.get("ZARIN_PORT", "8630"))
HOST = os.environ.get("ZARIN_HOST", "127.0.0.1")  # containers set 0.0.0.0

TELEMETRY_DIR = Path(os.environ.get("ZARIN_TELEMETRY_DIR", ROOT / "data" / "telemetry"))

# Optional operator token for the Control Center API. Unset (default) → open, which is
# fine for the loopback single-tenant demo. Set it before ANY non-loopback deploy and the
# `/api/admin/*` routes require the `X-Admin-Token` header. See docs/DEPLOYMENT_SPEC.md.
ADMIN_TOKEN = os.environ.get("ZARIN_ADMIN_TOKEN", "").strip()
MAX_QUESTION_LEN = 500  # cap free-text copilot questions (memory / prompt-size guard)

# --- AI copilot (OpenRouter) ---------------------------------------------------
# The AI layer is OPTIONAL. With no key the product runs fully offline on the
# deterministic engine; the LLM only ever rephrases numbers the engine computed.
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "").strip()
OPENROUTER_BASE_URL = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
# Free-model policy: a model is allowed iff its id ends with ':free' (OpenRouter's
# zero-price convention) OR is in FREE_ALLOWLIST. `openrouter/auto` is REJECTED —
# OpenRouter bills auto-routing at the selected model's standard rate.
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "deepseek/deepseek-chat-v3-0324:free").strip()
OPENROUTER_TIMEOUT = float(os.environ.get("OPENROUTER_TIMEOUT", "20"))
AI_MAX_TOKENS = int(os.environ.get("ZARIN_AI_MAX_TOKENS", "600"))

# --- Google Analytics 4 (optional external source) -----------------------------
GA4_PROPERTY_ID = os.environ.get("GA4_PROPERTY_ID", "").strip()
GOOGLE_APPLICATION_CREDENTIALS = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()

# --- Analytical thresholds (documented in docs/ANALYTICS.md) ---
MIN_PEERS = 5              # below this: suppress percentile benchmarks entirely
PREFERRED_PEERS = 8        # below this: fall back from scale-band to whole category
MIN_SESSIONS_INSIGHT = 100     # merchant-period sessions needed before friction insights
MIN_CUSTOMERS_RETENTION = 50   # customers needed before retention/repeat insights
MIN_SEGMENT_N = 30             # minimum sessions in a segment before quoting its rate

SUCCESS_SESSION = ("Verified",)          # a successful session
SETTLED_SESSION = ("Verified", "Paid")   # money settled at bank
OK_TRY = ("Verified", "Paid")            # a successful attempt

CURRENCY_NOTE = "همه مبالغ به ریال است."
FEE_CAVEAT = (
    "ستون adjusted_fee کارمزد واقعی زرین‌پال نیست؛ یک ضریب ثابت برای حفظ محرمانگی روی آن اعمال شده است. "
    "فقط برای مقایسه نسبی (روند، رتبه، سهم از درآمد) معتبر است و در محصول «شاخص نسبی کارمزد» نامیده می‌شود."
)
CUSTOMER_SCOPE_CAVEAT = (
    "شناسه کارت فقط برای تلاش‌های به سرانجام رسیده ثبت می‌شود و بین پذیرنده‌های مختلف مشترک نیست؛ "
    "بنابراین تحلیل مشتری فقط پرداخت‌کنندگان موفقِ همین پذیرنده را پوشش می‌دهد."
)
