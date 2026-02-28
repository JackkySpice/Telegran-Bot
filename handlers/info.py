"""How It Works explainer and portfolio viewer."""

from __future__ import annotations

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

import config
from complan import get_user_portfolio
from keyboards import MAIN_MENU


HOW_IT_WORKS = (
    "<b>❓ How does Vantage work?</b>\n\n"
    "1. Choose a plan (tap <b>Plans</b>)\n"
    "2. Tap <b>Invest</b> and follow the steps\n"
    "3. Send crypto to the address the bot provides\n"
    "4. Once payment is confirmed, your investment starts automatically\n"
    "5. You earn daily\n"
    "6. Every Sunday you can withdraw\n\n"
    "━━━━━━━━━━━━━━━━━━━━\n\n"
    "<b>Plan 1</b> — 50–250 TRX/USDT\n"
    "  18% profit in 60 days, unlock after 40 days\n\n"
    "<b>Plan 2</b> — 251–450 TRX/USDT\n"
    "  20% profit in 60 days, unlock after 30 days\n\n"
    "<b>Plan 3</b> — 451–650 TRX/USDT\n"
    "  22% profit in 60 days, unlock after 13 days\n\n"
    "━━━━━━━━━━━━━━━━━━━━\n\n"
    "<b>Referral Bonus</b> (optional):\n"
    "Level 1: 3% | Level 2–5: 1% each\n"
    "<i>Based on profit, not deposit.</i>\n\n"
    "<b>Withdrawal:</b> Every Sunday, 5% fee, min 30 TRX.\n"
    "Set your wallet first via the <b>Wallet</b> button.\n\n"
    "━━━━━━━━━━━━━━━━━━━━\n\n"
    "<b>Rules:</b>\n"
    "• 1 active per plan, max 3 at a time\n"
    "• Cannot repeat until the 60-day cycle ends\n"
    "• Inviting others is optional, not required to withdraw\n"
    "• If your payment is short, it won't activate. Contact admin.\n\n"
    "<i>You earn when we earn. Your capital is safe.</i>"
)


async def howitworks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        HOW_IT_WORKS, parse_mode="HTML", reply_markup=MAIN_MENU
    )


async def portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    investments = await get_user_portfolio(user_id)

    if not investments:
        await update.message.reply_text(
            "<b>📈 Portfolio</b>\n\n"
            "<i>You don't have any investments yet.</i>\n"
            "Tap <b>Plans</b> to see options.",
            parse_mode="HTML",
            reply_markup=MAIN_MENU,
        )
        return

    lines = ["<b>📈 Your Investments</b>\n"]
    for inv in investments:
        plan = config.PLANS.get(inv["plan_id"], {})
        pct_done = (
            (inv["earned_so_far"] / inv["total_profit"] * 100)
            if inv["total_profit"] > 0
            else 0
        )
        emoji = "🟢" if inv["status"] == "active" else "✅"
        lines.append(
            f"{emoji} <b>{plan.get('name', '?')}</b> | <code>{inv['amount']} {inv['currency']}</code>\n"
            f"  Earned: <code>{inv['earned_so_far']:.4f}/{inv['total_profit']:.4f}</code> ({pct_done:.1f}%)\n"
            f"  Daily:  <code>+{inv['daily_profit']:.4f} {inv['currency']}</code>\n"
            f"  Unlock: <code>{inv['unlocks_at'][:10]}</code> | End: <code>{inv['expires_at'][:10]}</code>"
        )

    await update.message.reply_text(
        "\n".join(lines), parse_mode="HTML", reply_markup=MAIN_MENU
    )


def register(app):
    app.add_handler(CommandHandler("howitworks", howitworks))
    app.add_handler(CommandHandler("portfolio", portfolio))
