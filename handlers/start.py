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
        "SELECT user_id FROM users WHERE user_id = ?", (user.id,)
    )

    referrer_id = None
    if context.args:
        ref_code = context.args[0]
        ref_row = await db.execute_fetchall(
            "SELECT user_id FROM users WHERE referral_code = ?", (ref_code,)
        )
        if ref_row:
            referrer_id = ref_row[0][0]

    if not existing:
        code = hashlib.md5(str(user.id).encode()).hexdigest()[:8]
        await db.execute(
            """INSERT INTO users (user_id, username, first_name, referred_by, referral_code)
               VALUES (?, ?, ?, ?, ?)""",
            (user.id, user.username, user.first_name, referrer_id, code),
        )
        await db.commit()

    row = await db.execute_fetchall(
        "SELECT referral_code FROM users WHERE user_id = ?", (user.id,)
    )
    ref_code = row[0][0]
    bot_username = (await context.bot.get_me()).username

    text = (
        f"Kumusta {user.first_name}! Welcome to Kimielbot! 🫶\n\n"
        "Dito mo makikita ang lahat ng kailangan mo para mag-invest at kumita.\n\n"
        "Commands:\n"
        "/plans - Tignan ang investment plans\n"
        "/invest - Mag-invest\n"
        "/portfolio - Status ng investments mo\n"
        "/balance - Tignan ang balance mo\n"
        "/withdraw - Mag-withdraw\n"
        "/referral - Referral link at stats mo\n"
        "/howitworks - Pano ba to gumagana?\n"
        "/help - Listahan ng commands\n\n"
        f"Referral link mo:\nhttps://t.me/{bot_username}?start={ref_code}"
    )
    await update.message.reply_text(text)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Kimielbot Commands:\n\n"
        "/start - Register / Main menu\n"
        "/plans - Tignan ang 3 investment plans\n"
        "/invest <plan> <amount> [currency] - Mag-invest\n"
        "   Halimbawa: /invest 1 100 TRX\n"
        "/portfolio - Lahat ng investments mo\n"
        "/balance - Current balance mo\n"
        "/withdraw <amount> [currency] - Mag-withdraw\n"
        "/referral - Referral link at earnings\n"
        "/howitworks - Paano gumagana ang system\n"
        "/help - Ito na to haha"
    )
    await update.message.reply_text(text)


def register(app):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
