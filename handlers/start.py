"""Start & registration handler."""

from __future__ import annotations

import hashlib

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from database import get_db


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

    row = await db.execute_fetchall(
        "SELECT referral_code FROM users WHERE user_id = ?", (user.id,)
    )
    ref_code = row[0][0]
    bot_username = (await context.bot.get_me()).username

    await update.message.reply_text(
        f"Welcome {user.first_name}! 🫶\n\n"
        "/plans - Investment plans\n"
        "/invest - Mag-invest\n"
        "/deposits - Deposit status\n"
        "/portfolio - Investment status\n"
        "/balance - Balance mo\n"
        "/setwallet - Set withdrawal address\n"
        "/mywallet - Current wallet\n"
        "/withdraw - Mag-withdraw (Sundays)\n"
        "/history - Withdrawal history\n"
        "/referral - Referral link\n"
        "/howitworks - Pano to?\n\n"
        f"Referral link:\nhttps://t.me/{bot_username}?start={ref_code}"
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Commands:\n"
        "/start - Register\n"
        "/plans - Plans\n"
        "/invest <plan> <amount> [TRX/USDT]\n"
        "/deposits - Deposit status\n"
        "/canceldeposit <id> - Cancel pending deposit\n"
        "/portfolio - Investments\n"
        "/balance - Balance\n"
        "/setwallet <address> - Set wallet\n"
        "/mywallet - View wallet\n"
        "/withdraw <amount> [TRX/USDT]\n"
        "/history - Withdrawal history\n"
        "/referral - Referral info\n"
        "/howitworks - How it works"
    )


def register(app):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
