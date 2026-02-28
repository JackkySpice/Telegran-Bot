"""How It Works explainer and portfolio viewer."""

from __future__ import annotations

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

import config
from complan import get_user_portfolio
from keyboards import MAIN_MENU


HOW_IT_WORKS = """Pano gumagana ang Kimielbot?

1. Pumili ng plan (tap Plans)
2. Tap Invest at sundan ang steps
3. Send crypto sa address na ibibigay ng bot
4. Pag confirmed na yung payment, automatic na mag-start ang investment mo
5. Araw-araw kumikita ka
6. Every Sunday, pwede ka mag-withdraw

3 Plans:

Plan 1 (50-250 TRX/USDT)
18% profit sa 60 days, unlock after 40 days

Plan 2 (251-450 TRX/USDT)
20% profit sa 60 days, unlock after 30 days

Plan 3 (451-650 TRX/USDT)
22% profit sa 60 days, unlock after 13 days

Referral Bonus (optional):
Level 1: 3% | Level 2-5: 1% each
Based sa profit, hindi sa deposit.

Withdrawal: Every Sunday, 5% fee, min 30 TRX.
Set wallet first via Wallet button.

Rules:
- 1 active per plan, max 3 sabay-sabay
- Hindi pwede ulitin hanggang di tapos ang 60 days
- Kahit walang invite, maka-withdraw ka
- Pag kulang ang binayad mo, hindi ma-aactivate. Contact admin.

You earn when we earn. Capital mo, safe."""


async def howitworks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HOW_IT_WORKS, reply_markup=MAIN_MENU)


async def portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    investments = await get_user_portfolio(user_id)

    if not investments:
        await update.message.reply_text(
            "Wala ka pang investment. Tap Plans to see options.",
            reply_markup=MAIN_MENU,
        )
        return

    lines = ["Investments mo:\n"]
    for inv in investments:
        plan = config.PLANS.get(inv["plan_id"], {})
        pct_done = (
            (inv["earned_so_far"] / inv["total_profit"] * 100)
            if inv["total_profit"] > 0
            else 0
        )
        emoji = "🟢" if inv["status"] == "active" else "✅"
        lines.append(
            f"{emoji} {plan.get('name', '?')} | {inv['amount']} {inv['currency']}\n"
            f"  Earned: {inv['earned_so_far']:.4f}/{inv['total_profit']:.4f} ({pct_done:.1f}%)\n"
            f"  Daily: +{inv['daily_profit']:.4f} {inv['currency']}\n"
            f"  Unlock: {inv['unlocks_at'][:10]} | End: {inv['expires_at'][:10]}"
        )

    await update.message.reply_text("\n".join(lines), reply_markup=MAIN_MENU)


def register(app):
    app.add_handler(CommandHandler("howitworks", howitworks))
    app.add_handler(CommandHandler("portfolio", portfolio))
