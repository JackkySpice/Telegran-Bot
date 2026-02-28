"""Reply keyboard definitions for the Telegram bot."""

from telegram import KeyboardButton, ReplyKeyboardMarkup

# Button text constants
BTN_INVEST = "💰 Invest"
BTN_PLANS = "📊 Plans"
BTN_PORTFOLIO = "📈 Portfolio"
BTN_BALANCE = "💵 Balance"
BTN_WITHDRAW = "🏧 Withdraw"
BTN_HISTORY = "📜 History"
BTN_WALLET = "👛 Wallet"
BTN_SET_WALLET = "👛 Set Wallet"
BTN_REFERRAL = "👥 Referral"
BTN_HOW = "❓ How It Works"
BTN_DEPOSITS = "📦 Deposits"
BTN_CANCEL = "❌ Cancel"
BTN_BACK = "🔙 Back"

BTN_PLAN_1 = "Plan 1"
BTN_PLAN_2 = "Plan 2"
BTN_PLAN_3 = "Plan 3"

BTN_TRX = "TRX"
BTN_USDT = "USDT"


MAIN_MENU = ReplyKeyboardMarkup(
    [
        [KeyboardButton(BTN_INVEST), KeyboardButton(BTN_PLANS), KeyboardButton(BTN_PORTFOLIO)],
        [KeyboardButton(BTN_BALANCE), KeyboardButton(BTN_WITHDRAW), KeyboardButton(BTN_HISTORY)],
        [KeyboardButton(BTN_WALLET), KeyboardButton(BTN_REFERRAL), KeyboardButton(BTN_HOW)],
        [KeyboardButton(BTN_DEPOSITS)],
    ],
    resize_keyboard=True,
)

PLAN_PICKER = ReplyKeyboardMarkup(
    [
        [KeyboardButton(BTN_PLAN_1), KeyboardButton(BTN_PLAN_2), KeyboardButton(BTN_PLAN_3)],
        [KeyboardButton(BTN_CANCEL)],
    ],
    resize_keyboard=True,
    one_time_keyboard=True,
)

CURRENCY_PICKER = ReplyKeyboardMarkup(
    [
        [KeyboardButton(BTN_TRX), KeyboardButton(BTN_USDT)],
        [KeyboardButton(BTN_CANCEL)],
    ],
    resize_keyboard=True,
    one_time_keyboard=True,
)

CANCEL_ONLY = ReplyKeyboardMarkup(
    [[KeyboardButton(BTN_CANCEL)]],
    resize_keyboard=True,
    one_time_keyboard=True,
)

WALLET_MENU = ReplyKeyboardMarkup(
    [
        [KeyboardButton(BTN_SET_WALLET)],
        [KeyboardButton(BTN_BACK)],
    ],
    resize_keyboard=True,
    one_time_keyboard=True,
)
