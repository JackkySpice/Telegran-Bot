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
            f"Plan {pid}: {p['profit_pct']}% in {p['duration_days']} days\n"
            f"  {p['min_amount']}-{p['max_amount']} TRX/USDT | unlock {p['lock_days']} days"
        )
    lines.append(
        f"\nWithdrawal: Every {config.PAYOUT_DAY}, {config.WITHDRAWAL_FEE_PCT}% fee, "
        f"min {config.MIN_WITHDRAWAL}\n"
        "1 active per plan, max 3 sabay.\n\n"
        "/invest <plan> <amount> [TRX/USDT]"
    )
    await update.message.reply_text("\n".join(lines))


async def invest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "/invest <plan> <amount> [TRX/USDT]\n"
            "Example: /invest 1 100 TRX"
        )
        return

    try:
        plan_id = int(context.args[0])
        amount = float(context.args[1])
    except ValueError:
        await update.message.reply_text("Plan at amount dapat numbers.")
        return

    currency = "TRX"
    if len(context.args) >= 3:
        currency = context.args[2].upper()
        if currency not in config.SUPPORTED_CURRENCIES:
            await update.message.reply_text("Supported: TRX, USDT")
            return

    if plan_id not in config.PLANS:
        await update.message.reply_text("Plan 1, 2, or 3 lang.")
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

    await update.message.reply_text(
        f"Invested! 🎉\n\n"
        f"{plan['name']} | {amount} {currency}\n"
        f"Profit: {result['total_profit']:.2f} {currency} ({plan['profit_pct']}%)\n"
        f"Daily: {result['daily_profit']:.4f} {currency}\n"
        f"Unlock: {plan['lock_days']} days | Duration: {plan['duration_days']} days"
    )


def register(app):
    app.add_handler(CommandHandler("plans", plans))
    app.add_handler(CommandHandler("invest", invest))
