"""Start, registration, and main-menu button router."""

from __future__ import annotations

import hashlib
import html

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes, MessageHandler, filters

from database import get_db
from keyboards import (
    BTN_BACK,
    BTN_BALANCE,
    BTN_DEPOSITS,
    BTN_HISTORY,
    BTN_HOW,
    BTN_PLANS,
    BTN_PORTFOLIO,
    BTN_REFERRAL,
    BTN_WALLET,
    MAIN_MENU,
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db = await get_db()

    existing = await db.execute_fetchall(
        "SELECT user_id, referred_by FROM users WHERE user_id = ?", (user.id,)
    )

    referrer_id = None
    if context.args:
        ref_code = context.args[0]
        ref_row = await db.execute_fetchall(
            "SELECT user_id FROM users WHERE referral_code = ?", (ref_code,)
        )
        if ref_row and ref_row[0][0] != user.id:
            referrer_id = ref_row[0][0]

    if not existing:
        code = hashlib.md5(str(user.id).encode()).hexdigest()[:8]
        await db.execute(
            """INSERT INTO users (user_id, username, first_name, referred_by, referral_code)
               VALUES (?, ?, ?, ?, ?)""",
            (user.id, user.username, user.first_name, referrer_id, code),
        )
        await db.commit()
    elif referrer_id and existing[0][1] is None:
        await db.execute(
            "UPDATE users SET referred_by = ? WHERE user_id = ? AND referred_by IS NULL",
            (referrer_id, user.id),
        )
        await db.commit()

    name = html.escape(user.first_name or "there")
    await update.message.reply_text(
        f"<b>Welcome to Vantage, {name}!</b>\n\n"
        "Use the buttons below to navigate.",
        parse_mode="HTML",
        reply_markup=MAIN_MENU,
    )


async def _route_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from handlers.invest import plans
    await plans(update, context)


async def _route_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from handlers.info import portfolio
    await portfolio(update, context)


async def _route_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from handlers.withdraw import balance
    await balance(update, context)


async def _route_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from handlers.withdraw import history
    await history(update, context)


async def _route_deposits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from handlers.invest import deposits
    await deposits(update, context)


async def _route_referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from handlers.referral import referral
    await referral(update, context)


async def _route_howitworks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from handlers.info import howitworks
    await howitworks(update, context)


async def _route_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from handlers.withdraw import mywallet_btn
    await mywallet_btn(update, context)


async def _route_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "<b>Main Menu</b>",
        parse_mode="HTML",
        reply_markup=MAIN_MENU,
    )


def register(app):
    app.add_handler(CommandHandler("start", start))

    app.add_handler(MessageHandler(filters.Text([BTN_PLANS]) & ~filters.COMMAND, _route_plans))
    app.add_handler(MessageHandler(filters.Text([BTN_PORTFOLIO]) & ~filters.COMMAND, _route_portfolio))
    app.add_handler(MessageHandler(filters.Text([BTN_BALANCE]) & ~filters.COMMAND, _route_balance))
    app.add_handler(MessageHandler(filters.Text([BTN_HISTORY]) & ~filters.COMMAND, _route_history))
    app.add_handler(MessageHandler(filters.Text([BTN_DEPOSITS]) & ~filters.COMMAND, _route_deposits))
    app.add_handler(MessageHandler(filters.Text([BTN_REFERRAL]) & ~filters.COMMAND, _route_referral))
    app.add_handler(MessageHandler(filters.Text([BTN_HOW]) & ~filters.COMMAND, _route_howitworks))
    app.add_handler(MessageHandler(filters.Text([BTN_WALLET]) & ~filters.COMMAND, _route_wallet))
    app.add_handler(MessageHandler(filters.Text([BTN_BACK]) & ~filters.COMMAND, _route_back))
