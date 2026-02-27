"""Investment handler."""

from __future__ import annotations

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

import config
from complan import can_user_invest, create_investment, validate_amount


async def plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = ["Investment Plans:\n"]
    for pid, p in config.PLANS.items():
        lines.append(
            f"Plan {pid}: {p['profit_pct']}% profit sa {p['duration_days']} days\n"
            f"   Amount: {p['min_amount']} - {p['max_amount']} TRX/USDT\n"
            f"   Withdrawal unlocks after {p['lock_days']} days\n"
        )
    lines.append(
        "Rules:\n"
        "- 1 active plan lang per tier\n"
        "- Max 3 active plans (isa sa bawat tier)\n"
        "- Hindi pwede ulitin ang plan hanggang di pa tapos ang 60 days\n"
        f"- Minimum withdrawal: {config.MIN_WITHDRAWAL} TRX\n\n"
        "Para mag-invest: /invest <plan> <amount> [TRX/USDT]\n"
        "Halimbawa: /invest 2 300 TRX"
    )
    await update.message.reply_text("\n".join(lines))


async def invest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "Usage: /invest <plan> <amount> [TRX/USDT]\n"
            "Halimbawa: /invest 1 100 TRX"
        )
        return

    try:
        plan_id = int(context.args[0])
        amount = float(context.args[1])
    except ValueError:
        await update.message.reply_text("Plan number at amount dapat numbers.")
        return

    currency = "TRX"
    if len(context.args) >= 3:
        currency = context.args[2].upper()
        if currency not in config.SUPPORTED_CURRENCIES:
            await update.message.reply_text(
                f"Currency hindi valid. Supported: {', '.join(config.SUPPORTED_CURRENCIES)}"
            )
            return

    if plan_id not in config.PLANS:
        await update.message.reply_text("Plan 1, 2, or 3 lang ang available.")
        return

    err = validate_amount(plan_id, amount)
    if err:
        await update.message.reply_text(err)
        return

    allowed, reason = await can_user_invest(user_id, plan_id)
    if not allowed:
        await update.message.reply_text(reason)
        return

    result = await create_investment(user_id, plan_id, amount, currency)
    plan = config.PLANS[plan_id]

    text = (
        f"Investment successful! 🎉\n\n"
        f"Plan: {plan['name']}\n"
        f"Amount: {amount} {currency}\n"
        f"Profit: {result['total_profit']:.2f} {currency} ({plan['profit_pct']}%)\n"
        f"Daily earning: {result['daily_profit']:.4f} {currency}\n"
        f"Duration: {plan['duration_days']} days\n"
        f"Withdrawal unlocks: after {plan['lock_days']} days\n\n"
        "Check /portfolio anytime para makita ang status mo."
    )
    await update.message.reply_text(text)


def register(app):
    app.add_handler(CommandHandler("plans", plans))
    app.add_handler(CommandHandler("invest", invest))
