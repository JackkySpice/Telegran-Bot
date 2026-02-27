"""How It Works explainer and portfolio viewer."""

from __future__ import annotations

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

import config
from complan import get_user_portfolio


HOW_IT_WORKS = """Pano gumagana ang Kimielbot? 🤔

Simple lang:
1. Pumili ka ng plan (Plan 1, 2, or 3)
2. Mag-invest ka ng TRX or USDT
3. Araw-araw kumikita ka (daily earnings)
4. Pag nag-unlock na, pwede ka na mag-withdraw

3 Plans:

Plan 1 (50-250 TRX/USDT)
- 18% profit sa 60 days
- Pwede mag-withdraw after 40 days

Plan 2 (251-450 TRX/USDT)
- 20% profit sa 60 days
- Pwede mag-withdraw after 30 days

Plan 3 (451-650 TRX/USDT)
- 22% profit sa 60 days
- Pwede mag-withdraw after 13 days

Mas malaki investment mo, mas mataas yung profit percentage at mas mabilis mag-unlock.

Referral Bonus:
Level 1: 3% ng investment ng invite mo
Level 2-5: 1% each

Mga rules:
- 1 lang na active per plan (pwede ka mag Plan 1, Plan 2, at Plan 3 nang sabay)
- Hindi pwede ulitin ang plan hanggang di pa tapos ang 60 days
- Minimum withdrawal: 30 TRX

Basically, you earn when we earn. Safe ang capital mo. 💪

Questions? Chat lang kayo dito!"""


async def howitworks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HOW_IT_WORKS)


async def portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    investments = await get_user_portfolio(user_id)

    if not investments:
        await update.message.reply_text(
            "Wala ka pang investment. Check /plans para makita ang options!"
        )
        return

    lines = ["Your Investments:\n"]
    for inv in investments:
        plan = config.PLANS.get(inv["plan_id"], {})
        pct_done = (
            (inv["earned_so_far"] / inv["total_profit"] * 100)
            if inv["total_profit"] > 0
            else 0
        )
        status_emoji = "🟢" if inv["status"] == "active" else "✅"
        lines.append(
            f"{status_emoji} {plan.get('name', 'Plan ?')} | "
            f"{inv['amount']} {inv['currency']}\n"
            f"   Earned: {inv['earned_so_far']:.4f} / {inv['total_profit']:.4f} "
            f"({pct_done:.1f}%)\n"
            f"   Daily: {inv['daily_profit']:.4f} {inv['currency']}\n"
            f"   Unlock: {inv['unlocks_at'][:10]} | "
            f"Expires: {inv['expires_at'][:10]}\n"
            f"   Status: {inv['status']}\n"
        )

    await update.message.reply_text("\n".join(lines))


def register(app):
    app.add_handler(CommandHandler("howitworks", howitworks))
    app.add_handler(CommandHandler("portfolio", portfolio))
