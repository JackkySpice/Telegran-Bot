import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_USER_IDS = [
    int(uid.strip())
    for uid in os.getenv("ADMIN_USER_IDS", "").split(",")
    if uid.strip()
]

DB_PATH = os.getenv("DB_PATH", "kimielbot.db")

# CoinPayments
CP_API_VERSION = int(os.getenv("CP_API_VERSION", "1"))  # 1 = legacy, 2 = current (recommended)
CP_PUBLIC_KEY = os.getenv("CP_PUBLIC_KEY", "")           # v1: API public key
CP_PRIVATE_KEY = os.getenv("CP_PRIVATE_KEY", "")         # v1: API private key / v2: client secret
CP_IPN_SECRET = os.getenv("CP_IPN_SECRET", "")           # v1: IPN secret
CP_MERCHANT_ID = os.getenv("CP_MERCHANT_ID", "")         # v1: merchant ID
CP_CLIENT_ID = os.getenv("CP_CLIENT_ID", "")             # v2: integration client ID
IPN_URL = os.getenv("IPN_URL", "")
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "8080"))

PLANS = {
    1: {
        "name": "Plan 1",
        "profit_pct": 18.0,
        "duration_days": 60,
        "min_amount": 50,
        "max_amount": 250,
        "lock_days": 40,
    },
    2: {
        "name": "Plan 2",
        "profit_pct": 20.0,
        "duration_days": 60,
        "min_amount": 251,
        "max_amount": 450,
        "lock_days": 30,
    },
    3: {
        "name": "Plan 3",
        "profit_pct": 22.0,
        "duration_days": 60,
        "min_amount": 451,
        "max_amount": 650,
        "lock_days": 13,
    },
}

MIN_WITHDRAWAL = 30  # TRX

WITHDRAWAL_FEE_PCT = 5.0

PAYOUT_DAY = "Sunday"

PROFIT_SPLIT = {
    "users": 70.0,
    "reserve": 20.0,
    "team": 10.0,
}

REFERRAL_LEVELS = {
    1: 3.0,
    2: 1.0,
    3: 1.0,
    4: 1.0,
    5: 1.0,
}

REFERRAL_ON_PROFIT = True

MAX_ACTIVE_PLANS_PER_USER = 3

SUPPORTED_CURRENCIES = ["TRX", "USDT"]

DEPOSIT_TIMEOUT_HOURS = 6
