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
