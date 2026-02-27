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

REFERRAL_LEVELS = {
    1: 3.0,
    2: 1.0,
    3: 1.0,
    4: 1.0,
    5: 1.0,
}

MAX_ACTIVE_PLANS_PER_USER = 3

SUPPORTED_CURRENCIES = ["TRX", "USDT"]
