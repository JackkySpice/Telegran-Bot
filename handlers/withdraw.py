"""Withdrawal & wallet handlers with button-driven ConversationHandlers."""

from __future__ import annotations

from datetime import datetime, timezone

from telegram import Update
from telegram.ext import (
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import config
from complan import calculate_withdrawal_fee
from database import get_db
from keyboards import (
    BTN_CANCEL,
    BTN_SET_WALLET,
    BTN_TRX,
    BTN_USDT,
    BTN_WALLET,
    BTN_WITHDRAW,
    CANCEL_ONLY,
    CURRENCY_PICKER,
    MAIN_MENU,
    WALLET_MENU,
)

WD_ENTER_AMOUNT, WD_PICK_CURRENCY = range(2)
SW_ENTER_ADDRESS = 0


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db = await get_db()
    row = await db.execute_fetchall(
        "SELECT balance_trx, balance_usdt FROM users WHERE user_id = ?", (user_id,)
    )
    if not row:
        await update.message.reply_text("Please register first by tapping Start.", reply_markup=MAIN_MENU)
        return

    trx, usdt = row[0]
    await update.message.reply_text(
        f"Your Balance:\n"
        f"TRX: {trx:.4f}\n"
        f"USDT: {usdt:.4f}\n\n"
        f"Min withdrawal: {config.MIN_WITHDRAWAL}\n"
        f"Fee: {config.WITHDRAWAL_FEE_PCT}%\n"
        f"Schedule: Every {config.PAYOUT_DAY}",
        reply_markup=MAIN_MENU,
    )


# --- Wallet button (shows info + sub-menu) ---

async def mywallet_btn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db = await get_db()
    row = await db.execute_fetchall(
        "SELECT wallet_address FROM users WHERE user_id = ?", (user_id,)
    )
    if not row:
        await update.message.reply_text("Please register first by tapping Start.", reply_markup=MAIN_MENU)
        return

    addr = row[0][0]
    if addr:
        await update.message.reply_text(
            f"Your wallet: {addr}\n\nTap Set Wallet to change it.",
            reply_markup=WALLET_MENU,
        )
    else:
        await update.message.reply_text(
            "You don't have a wallet set yet. Tap Set Wallet to add one.",
            reply_markup=WALLET_MENU,
        )


# --- Set-wallet conversation ---

async def setwallet_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Send me your TRX wallet address:",
        reply_markup=CANCEL_ONLY,
    )
    return SW_ENTER_ADDRESS


async def setwallet_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    address = update.message.text.strip()

    if len(address) < 20:
        await update.message.reply_text(
            "Invalid address (too short). Try again:",
            reply_markup=CANCEL_ONLY,
        )
        return SW_ENTER_ADDRESS

    db = await get_db()
    await db.execute(
        "UPDATE users SET wallet_address = ? WHERE user_id = ?",
        (address, user_id),
    )
    await db.commit()
    await update.message.reply_text(f"Wallet saved: {address}", reply_markup=MAIN_MENU)
    return ConversationHandler.END


async def setwallet_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Cancelled.", reply_markup=MAIN_MENU)
    return ConversationHandler.END


# --- Withdraw conversation ---

async def withdraw_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    db = await get_db()

    now = datetime.now(timezone.utc)
    if now.strftime("%A") != config.PAYOUT_DAY:
        await update.message.reply_text(
            f"Withdrawals are only available on {config.PAYOUT_DAY}. Come back then!",
            reply_markup=MAIN_MENU,
        )
        return ConversationHandler.END

    user_row = await db.execute_fetchall(
        "SELECT wallet_address FROM users WHERE user_id = ?", (user_id,)
    )
    if not user_row:
        await update.message.reply_text("Please register first by tapping Start.", reply_markup=MAIN_MENU)
        return ConversationHandler.END

    if not user_row[0][0]:
        await update.message.reply_text(
            "Please set your wallet address first. Tap 👛 Wallet.",
            reply_markup=MAIN_MENU,
        )
        return ConversationHandler.END

    active_inv = await db.execute_fetchall(
        """SELECT id, unlocks_at FROM investments
           WHERE user_id = ? AND status = 'active'
           ORDER BY unlocks_at ASC""",
        (user_id,),
    )
    all_locked = True
    for inv in active_inv:
        unlock_str = inv[1]
        if unlock_str and datetime.fromisoformat(unlock_str) <= now:
            all_locked = False
            break

    if active_inv and all_locked:
        nearest = min(
            datetime.fromisoformat(inv[1]) for inv in active_inv if inv[1]
        )
        days_left = (nearest - now).days
        await update.message.reply_text(
            f"Still in lock period. Unlocks in {days_left} day(s).",
            reply_markup=MAIN_MENU,
        )
        return ConversationHandler.END

    await update.message.reply_text("Enter withdrawal amount:", reply_markup=CANCEL_ONLY)
    return WD_ENTER_AMOUNT


async def withdraw_enter_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        amount = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Enter a valid number:", reply_markup=CANCEL_ONLY)
        return WD_ENTER_AMOUNT

    if amount <= 0:
        await update.message.reply_text("Amount must be positive:", reply_markup=CANCEL_ONLY)
        return WD_ENTER_AMOUNT

    if amount < config.MIN_WITHDRAWAL:
        await update.message.reply_text(
            f"Minimum withdrawal: {config.MIN_WITHDRAWAL}. Try again:",
            reply_markup=CANCEL_ONLY,
        )
        return WD_ENTER_AMOUNT

    context.user_data["wd_amount"] = amount
    await update.message.reply_text("Choose currency:", reply_markup=CURRENCY_PICKER)
    return WD_PICK_CURRENCY


async def withdraw_pick_currency(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    currency = update.message.text.strip().upper()
    if currency not in config.SUPPORTED_CURRENCIES:
        await update.message.reply_text("Pick TRX or USDT:", reply_markup=CURRENCY_PICKER)
        return WD_PICK_CURRENCY

    user_id = update.effective_user.id
    amount = context.user_data.pop("wd_amount")
    db = await get_db()

    user_row = await db.execute_fetchall(
        "SELECT wallet_address FROM users WHERE user_id = ?", (user_id,)
    )
    wallet_address = user_row[0][0]

    fee, net = calculate_withdrawal_fee(amount)

    balance_col = "balance_trx" if currency == "TRX" else "balance_usdt"
    result = await db.execute(
        f"UPDATE users SET {balance_col} = {balance_col} - ? "
        f"WHERE user_id = ? AND {balance_col} >= ?",
        (amount, user_id, amount),
    )
    if result.rowcount == 0:
        current = await db.execute_fetchall(
            f"SELECT {balance_col} FROM users WHERE user_id = ?", (user_id,)
        )
        bal = current[0][0] if current else 0
        await update.message.reply_text(
            f"Insufficient balance. Your balance: {bal:.4f} {currency}.",
            reply_markup=MAIN_MENU,
        )
        return ConversationHandler.END

    await db.execute(
        """INSERT INTO withdrawals (user_id, amount, fee, net_amount, currency, wallet_address, status)
           VALUES (?, ?, ?, ?, ?, ?, 'pending')""",
        (user_id, amount, fee, net, currency, wallet_address),
    )
    await db.commit()

    await update.message.reply_text(
        f"Withdrawal submitted!\n\n"
        f"Amount: {amount} {currency}\n"
        f"Fee ({config.WITHDRAWAL_FEE_PCT}%): {fee:.4f} {currency}\n"
        f"You receive: {net:.4f} {currency}\n"
        f"To: {wallet_address}\n"
        "Status: Pending",
        reply_markup=MAIN_MENU,
    )
    return ConversationHandler.END


async def withdraw_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("wd_amount", None)
    await update.message.reply_text("Cancelled.", reply_markup=MAIN_MENU)
    return ConversationHandler.END


async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db = await get_db()

    rows = await db.execute_fetchall(
        """SELECT id, amount, fee, net_amount, currency, wallet_address, status, created_at
           FROM withdrawals WHERE user_id = ?
           ORDER BY created_at DESC LIMIT 10""",
        (user_id,),
    )

    if not rows:
        await update.message.reply_text("No withdrawals yet.", reply_markup=MAIN_MENU)
        return

    lines = ["Withdrawal History:\n"]
    for r in rows:
        wd_id, amount, fee, net, currency, wallet, status, created = r
        emoji = {"pending": "⏳", "approved": "✅", "rejected": "❌"}.get(status, "?")
        lines.append(
            f"{emoji} #{wd_id} | {net} {currency} | {status}\n"
            f"  Fee: {fee} | {created[:16]}"
        )

    await update.message.reply_text("\n".join(lines), reply_markup=MAIN_MENU)


def register(app):
    setwallet_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Text([BTN_SET_WALLET]) & ~filters.COMMAND, setwallet_start),
            CommandHandler("setwallet", setwallet_start),
        ],
        states={
            SW_ENTER_ADDRESS: [
                MessageHandler(filters.Text([BTN_CANCEL]) & ~filters.COMMAND, setwallet_cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, setwallet_receive),
            ],
        },
        fallbacks=[
            MessageHandler(filters.Text([BTN_CANCEL]) & ~filters.COMMAND, setwallet_cancel),
            CommandHandler("cancel", setwallet_cancel),
        ],
    )

    withdraw_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Text([BTN_WITHDRAW]) & ~filters.COMMAND, withdraw_start),
            CommandHandler("withdraw", withdraw_start),
        ],
        states={
            WD_ENTER_AMOUNT: [
                MessageHandler(filters.Text([BTN_CANCEL]) & ~filters.COMMAND, withdraw_cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_enter_amount),
            ],
            WD_PICK_CURRENCY: [
                MessageHandler(filters.Text([BTN_CANCEL]) & ~filters.COMMAND, withdraw_cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_pick_currency),
            ],
        },
        fallbacks=[
            MessageHandler(filters.Text([BTN_CANCEL]) & ~filters.COMMAND, withdraw_cancel),
            CommandHandler("cancel", withdraw_cancel),
        ],
    )

    app.add_handler(setwallet_conv)
    app.add_handler(withdraw_conv)

    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("mywallet", mywallet_btn))
    app.add_handler(CommandHandler("history", history))
