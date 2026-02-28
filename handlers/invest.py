"""Investment handler with button-driven ConversationHandlers and CoinPayments deposit flow."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import (
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import config
from coinpayments import CoinPaymentsError, create_transaction
from complan import can_user_invest, validate_amount
from database import get_db
from keyboards import (
    BTN_CANCEL,
    BTN_CANCEL_DEPOSIT,
    BTN_INVEST,
    BTN_PLAN_1,
    BTN_PLAN_2,
    BTN_PLAN_3,
    BTN_TRX,
    BTN_USDT,
    CANCEL_ONLY,
    CURRENCY_PICKER,
    MAIN_MENU,
    PLAN_PICKER,
)

logger = logging.getLogger(__name__)

PICK_PLAN, ENTER_AMOUNT, PICK_CURRENCY = range(3)
CD_PICK_DEPOSIT = 0

PLAN_TEXT_MAP = {BTN_PLAN_1: 1, BTN_PLAN_2: 2, BTN_PLAN_3: 3}


async def _ensure_registered(update: Update) -> bool:
    db = await get_db()
    row = await db.execute_fetchall(
        "SELECT user_id FROM users WHERE user_id = ?",
        (update.effective_user.id,),
    )
    if not row:
        await update.message.reply_text(
            "Please register first by tapping Start.",
            reply_markup=MAIN_MENU,
        )
        return False
    return True


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
        "1 active per plan, max 3 at a time.\n\n"
        "Tap 💰 Invest to start."
    )
    await update.message.reply_text("\n".join(lines), reply_markup=MAIN_MENU)


# --- Invest conversation ---

async def invest_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _ensure_registered(update):
        return ConversationHandler.END

    await update.message.reply_text(
        "Choose a plan:", reply_markup=PLAN_PICKER
    )
    return PICK_PLAN


async def invest_pick_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    plan_id = PLAN_TEXT_MAP.get(text)
    if plan_id is None:
        await update.message.reply_text(
            "Pick a plan from the buttons below:", reply_markup=PLAN_PICKER
        )
        return PICK_PLAN

    plan = config.PLANS[plan_id]
    context.user_data["invest_plan"] = plan_id

    await update.message.reply_text(
        f"{plan['name']}: {plan['profit_pct']}% in {plan['duration_days']} days\n"
        f"Range: {plan['min_amount']} - {plan['max_amount']}\n\n"
        "Enter amount:",
        reply_markup=CANCEL_ONLY,
    )
    return ENTER_AMOUNT


async def invest_enter_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        amount = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text(
            "Enter a valid number:", reply_markup=CANCEL_ONLY
        )
        return ENTER_AMOUNT

    if amount <= 0:
        await update.message.reply_text(
            "Amount must be positive:", reply_markup=CANCEL_ONLY
        )
        return ENTER_AMOUNT

    plan_id = context.user_data["invest_plan"]
    err = validate_amount(plan_id, amount)
    if err:
        await update.message.reply_text(f"{err}\n\nEnter amount:", reply_markup=CANCEL_ONLY)
        return ENTER_AMOUNT

    context.user_data["invest_amount"] = amount
    await update.message.reply_text("Choose currency:", reply_markup=CURRENCY_PICKER)
    return PICK_CURRENCY


async def invest_pick_currency(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    currency = update.message.text.strip().upper()
    if currency not in config.SUPPORTED_CURRENCIES:
        await update.message.reply_text(
            "Pick TRX or USDT:", reply_markup=CURRENCY_PICKER
        )
        return PICK_CURRENCY

    plan_id = context.user_data["invest_plan"]
    amount = context.user_data["invest_amount"]
    user_id = update.effective_user.id

    allowed, reason = await can_user_invest(user_id, plan_id)
    if not allowed:
        await update.message.reply_text(reason, reply_markup=MAIN_MENU)
        return ConversationHandler.END

    db = await get_db()
    pending = await db.execute_fetchall(
        "SELECT id FROM deposits WHERE user_id = ? AND plan_id = ? AND status = 'pending'",
        (user_id, plan_id),
    )
    if pending:
        await update.message.reply_text(
            "You still have a pending deposit for this plan.\n"
            "Tap 📦 Deposits to view it, or wait for it to expire.",
            reply_markup=MAIN_MENU,
        )
        return ConversationHandler.END

    custom_data = f"{user_id}|{plan_id}"

    if not config.CP_PUBLIC_KEY:
        deposit_id = await _create_offline_deposit(user_id, plan_id, amount, currency)
        await update.message.reply_text(
            f"Deposit #{deposit_id} created (offline mode)\n\n"
            f"Plan {plan_id} | {amount} {currency}\n"
            "Admin will confirm manually.",
            reply_markup=MAIN_MENU,
        )
        return ConversationHandler.END

    try:
        tx = await create_transaction(
            amount=amount,
            currency=currency,
            ipn_url=config.IPN_URL,
            custom=custom_data,
        )
    except CoinPaymentsError as e:
        logger.error("CoinPayments error: %s", e)
        await update.message.reply_text(
            "Payment system error. Try again later.",
            reply_markup=MAIN_MENU,
        )
        return ConversationHandler.END

    await db.execute(
        """INSERT INTO deposits
           (user_id, plan_id, amount, currency, cp_txn_id, deposit_address, status)
           VALUES (?, ?, ?, ?, ?, ?, 'pending')""",
        (user_id, plan_id, amount, currency, tx["txn_id"], tx["address"]),
    )
    await db.commit()

    plan = config.PLANS[plan_id]
    timeout_hrs = config.DEPOSIT_TIMEOUT_HOURS

    await update.message.reply_text(
        f"Send {amount} {currency} to this address:\n\n"
        f"`{tx['address']}`\n\n"
        f"Plan: {plan['name']} ({plan['profit_pct']}% in {plan['duration_days']} days)\n"
        f"TXN: {tx['txn_id']}\n"
        f"Expires in {timeout_hrs} hours.\n\n"
        "Investment starts once payment is confirmed.",
        parse_mode="Markdown",
        reply_markup=MAIN_MENU,
    )
    return ConversationHandler.END


async def invest_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("invest_plan", None)
    context.user_data.pop("invest_amount", None)
    await update.message.reply_text("Cancelled.", reply_markup=MAIN_MENU)
    return ConversationHandler.END


async def _create_offline_deposit(user_id: int, plan_id: int, amount: float, currency: str) -> int:
    db = await get_db()
    await db.execute(
        """INSERT INTO deposits
           (user_id, plan_id, amount, currency, cp_txn_id, deposit_address, status)
           VALUES (?, ?, ?, ?, ?, ?, 'pending')""",
        (user_id, plan_id, amount, currency, None, "manual", "pending"),
    )
    await db.commit()
    row = await db.execute_fetchall("SELECT last_insert_rowid()")
    return row[0][0]


async def deposits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from keyboards import _deposits_keyboard

    user_id = update.effective_user.id
    db = await get_db()

    rows = await db.execute_fetchall(
        """SELECT id, plan_id, amount, currency, status, deposit_address, cp_txn_id, created_at
           FROM deposits WHERE user_id = ?
           ORDER BY created_at DESC LIMIT 10""",
        (user_id,),
    )

    if not rows:
        await update.message.reply_text(
            "No deposits yet. Tap 💰 Invest to start.",
            reply_markup=MAIN_MENU,
        )
        return

    has_pending = False
    lines = ["Your Deposits:\n"]
    for r in rows:
        dep_id, plan_id, amount, currency, status, addr, txn_id, created = r
        if status == "pending":
            has_pending = True
        emoji = {
            "pending": "⏳", "confirmed": "✅", "expired": "❌",
            "cancelled": "❌", "underpaid": "⚠️",
        }.get(status, "?")
        line = (
            f"{emoji} #{dep_id} | Plan {plan_id} | {amount} {currency} | {status}\n"
            f"  {created[:16]}"
        )
        if status == "pending" and addr and addr != "manual":
            line += f"\n  Send to: {addr}"
        lines.append(line)

    keyboard = _deposits_keyboard(has_pending)
    await update.message.reply_text("\n".join(lines), reply_markup=keyboard)


# --- Cancel-deposit conversation ---

async def cancel_deposit_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    db = await get_db()
    pending = await db.execute_fetchall(
        "SELECT id, plan_id, amount, currency, created_at FROM deposits WHERE user_id = ? AND status = 'pending' ORDER BY created_at DESC",
        (user_id,),
    )

    if not pending:
        await update.message.reply_text("You have no pending deposits to cancel.", reply_markup=MAIN_MENU)
        return ConversationHandler.END

    lines = ["Your pending deposits:\n"]
    for r in pending:
        lines.append(f"  #{r[0]} | Plan {r[1]} | {r[2]} {r[3]} | {r[4][:16]}")
    lines.append("\nEnter the deposit # to cancel:")

    await update.message.reply_text("\n".join(lines), reply_markup=CANCEL_ONLY)
    return CD_PICK_DEPOSIT


async def cancel_deposit_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    text = update.message.text.strip().lstrip("#")

    try:
        dep_id = int(text)
    except ValueError:
        await update.message.reply_text("Enter a valid deposit number:", reply_markup=CANCEL_ONLY)
        return CD_PICK_DEPOSIT

    db = await get_db()
    row = await db.execute_fetchall(
        "SELECT id, user_id, status FROM deposits WHERE id = ?",
        (dep_id,),
    )

    if not row:
        await update.message.reply_text("Deposit not found. Try again:", reply_markup=CANCEL_ONLY)
        return CD_PICK_DEPOSIT

    if row[0][1] != user_id:
        await update.message.reply_text("That deposit doesn't belong to you. Try again:", reply_markup=CANCEL_ONLY)
        return CD_PICK_DEPOSIT

    if row[0][2] != "pending":
        await update.message.reply_text(
            f"Deposit #{dep_id} is {row[0][2]}. It can no longer be cancelled.",
            reply_markup=MAIN_MENU,
        )
        return ConversationHandler.END

    await db.execute(
        "UPDATE deposits SET status = 'cancelled' WHERE id = ?",
        (dep_id,),
    )
    await db.commit()

    await update.message.reply_text(f"Deposit #{dep_id} cancelled.", reply_markup=MAIN_MENU)
    return ConversationHandler.END


async def cancel_deposit_abort(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Cancelled.", reply_markup=MAIN_MENU)
    return ConversationHandler.END


def register(app):
    invest_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Text([BTN_INVEST]) & ~filters.COMMAND, invest_start),
            CommandHandler("invest", invest_start),
        ],
        states={
            PICK_PLAN: [
                MessageHandler(filters.Text([BTN_CANCEL]) & ~filters.COMMAND, invest_cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, invest_pick_plan),
            ],
            ENTER_AMOUNT: [
                MessageHandler(filters.Text([BTN_CANCEL]) & ~filters.COMMAND, invest_cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, invest_enter_amount),
            ],
            PICK_CURRENCY: [
                MessageHandler(filters.Text([BTN_CANCEL]) & ~filters.COMMAND, invest_cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, invest_pick_currency),
            ],
        },
        fallbacks=[
            MessageHandler(filters.Text([BTN_CANCEL]) & ~filters.COMMAND, invest_cancel),
            CommandHandler("cancel", invest_cancel),
        ],
    )

    cancel_dep_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Text([BTN_CANCEL_DEPOSIT]) & ~filters.COMMAND, cancel_deposit_start),
        ],
        states={
            CD_PICK_DEPOSIT: [
                MessageHandler(filters.Text([BTN_CANCEL]) & ~filters.COMMAND, cancel_deposit_abort),
                MessageHandler(filters.TEXT & ~filters.COMMAND, cancel_deposit_pick),
            ],
        },
        fallbacks=[
            MessageHandler(filters.Text([BTN_CANCEL]) & ~filters.COMMAND, cancel_deposit_abort),
            CommandHandler("cancel", cancel_deposit_abort),
        ],
    )

    app.add_handler(invest_conv)
    app.add_handler(cancel_dep_conv)

    app.add_handler(CommandHandler("plans", plans))
    app.add_handler(CommandHandler("deposits", deposits))
