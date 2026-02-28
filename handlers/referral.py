"""Referral handler."""

from __future__ import annotations

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

import config
from complan import get_referral_stats
from database import get_db
from keyboards import MAIN_MENU


async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db = await get_db()

    row = await db.execute_fetchall(
        "SELECT referral_code FROM users WHERE user_id = ?", (user_id,)
    )
    if not row:
        await update.message.reply_text("Please register first by tapping Start.", reply_markup=MAIN_MENU)
        return

    ref_code = row[0][0]
    bot_username = (await context.bot.get_me()).username
    link = f"https://t.me/{bot_username}?start={ref_code}"

    direct_count = await db.execute_fetchall(
        "SELECT COUNT(*) FROM users WHERE referred_by = ?", (user_id,)
    )
    direct = direct_count[0][0]

    stats = await get_referral_stats(user_id)

    basis = "profit" if config.REFERRAL_ON_PROFIT else "deposit"
    lines = [
        f"Referral link: {link}\n",
        f"Direct referrals: {direct}",
        f"Commission basis: {basis}\n",
    ]

    for level, pct in config.REFERRAL_LEVELS.items():
        lvl_data = stats["levels"].get(level, {"total": 0, "count": 0})
        lines.append(
            f"L{level} ({pct}%): {lvl_data['total']:.4f} ({lvl_data['count']}x)"
        )

    lines.append(f"\nTotal: {stats['grand_total']:.4f}")
    lines.append("Inviting others is optional, not required to withdraw.")

    await update.message.reply_text("\n".join(lines), reply_markup=MAIN_MENU)


def register(app):
    app.add_handler(CommandHandler("referral", referral))
