"""Referral handler."""

from __future__ import annotations

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

import config
from complan import get_referral_stats
from database import get_db


async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db = await get_db()

    row = await db.execute_fetchall(
        "SELECT referral_code FROM users WHERE user_id = ?", (user_id,)
    )
    if not row:
        await update.message.reply_text("Register ka muna gamit /start.")
        return

    ref_code = row[0][0]
    bot_username = (await context.bot.get_me()).username
    link = f"https://t.me/{bot_username}?start={ref_code}"

    direct_count = await db.execute_fetchall(
        "SELECT COUNT(*) FROM users WHERE referred_by = ?", (user_id,)
    )
    direct = direct_count[0][0]

    stats = await get_referral_stats(user_id)

    lines = [
        "Referral Info:\n",
        f"Link mo: {link}\n",
        f"Direct referrals: {direct}\n",
        "Referral commissions:\n",
    ]

    for level, pct in config.REFERRAL_LEVELS.items():
        lvl_data = stats["levels"].get(level, {"total": 0, "count": 0})
        lines.append(
            f"  Level {level} ({pct}%): {lvl_data['total']:.4f} TRX "
            f"({lvl_data['count']} transactions)"
        )

    lines.append(f"\nTotal earnings: {stats['grand_total']:.4f} TRX")
    lines.append(
        "\nShare mo lang yung link sa friends mo. "
        "Pag nag-invest sila, kumikita ka agad!"
    )

    await update.message.reply_text("\n".join(lines))


def register(app):
    app.add_handler(CommandHandler("referral", referral))
