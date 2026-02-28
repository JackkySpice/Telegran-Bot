"""How It Works explainer and portfolio viewer."""

from __future__ import annotations

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

import config
from complan import get_user_portfolio
from keyboards import MAIN_MENU


HOW_IT_WORKS = """How does Vantage work?

1. Choose a plan (tap Plans)
2. Tap Invest and follow the steps
3. Send crypto to the address the bot provides
4. Once payment is confirmed, your investment starts automatically
5. You earn daily
6. Every Sunday you can withdraw

3 Plans:

Plan 1 (50-250 TRX/USDT)
18% profit in 60 days, unlock after 40 days

Plan 2 (251-450 TRX/USDT)
20% profit in 60 days, unlock after 30 days

Plan 3 (451-650 TRX/USDT)
22% profit in 60 days, unlock after 13 days

Referral Bonus (optional):
Level 1: 3% | Level 2-5: 1% each
Based on profit, not deposit.

Withdrawal: Every Sunday, 5% fee, min 30 TRX.
Set your wallet first via the Wallet button.

Rules:
- 1 active per plan, max 3 at a time
- Cannot repeat until the 60-day cycle ends
- Inviting others is optional, not required to withdraw
- If your payment is short, it won't activate. Contact admin.

You earn when we earn. Your capital is safe."""


async def howitworks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HOW_IT_WORKS, reply_markup=MAIN_MENU)


async def portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    investments = await get_user_portfolio(user_id)

    if not investments:
        await update.message.reply_text(
            "You don't have any investments yet. Tap Plans to see options.",
            reply_markup=MAIN_MENU,
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
