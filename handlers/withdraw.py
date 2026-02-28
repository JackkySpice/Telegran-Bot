"""Withdrawal handler with wallet address collection."""

from __future__ import annotations

from datetime import datetime, timezone

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

import config
from complan import calculate_withdrawal_fee
from database import get_db


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db = await get_db()
    row = await db.execute_fetchall(
        "SELECT balance_trx, balance_usdt FROM users WHERE user_id = ?", (user_id,)
    )
    if not row:
        await update.message.reply_text("Register ka muna: /start")
        return

    trx, usdt = row[0]
    await update.message.reply_text(
        f"Balance mo:\n"
        f"TRX: {trx:.4f}\n"
        f"USDT: {usdt:.4f}\n\n"
        f"Min withdrawal: {config.MIN_WITHDRAWAL}\n"
        f"Fee: {config.WITHDRAWAL_FEE_PCT}%\n"
        f"Schedule: Every {config.PAYOUT_DAY}"
    )


async def setwallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set wallet address: /setwallet <address>"""
    user_id = update.effective_user.id
    db = await get_db()

    row = await db.execute_fetchall(
        "SELECT user_id FROM users WHERE user_id = ?", (user_id,)
    )
    if not row:
        await update.message.reply_text("Register ka muna: /start")
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: /setwallet <TRX_address>\n"
            "Example: /setwallet TXyz123..."
        )
        return

    address = context.args[0].strip()
    if len(address) < 20:
        await update.message.reply_text("Invalid address. Too short.")
        return

    await db.execute(
        "UPDATE users SET wallet_address = ? WHERE user_id = ?",
        (address, user_id),
    )
    await db.commit()
    await update.message.reply_text(f"Wallet saved: {address}")


async def mywallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show current wallet address."""
    user_id = update.effective_user.id
    db = await get_db()
    row = await db.execute_fetchall(
        "SELECT wallet_address FROM users WHERE user_id = ?", (user_id,)
    )
    if not row:
        await update.message.reply_text("Register ka muna: /start")
        return

    addr = row[0][0]
    if addr:
        await update.message.reply_text(f"Wallet mo: {addr}\n\nPalitan: /setwallet <new_address>")
    else:
        await update.message.reply_text("Wala ka pang wallet. /setwallet <TRX_address>")


async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db = await get_db()

    now = datetime.now(timezone.utc)
    if now.strftime("%A") != config.PAYOUT_DAY:
        await update.message.reply_text(
            f"Withdrawal is every {config.PAYOUT_DAY} lang. Balik ka sa {config.PAYOUT_DAY}!"
        )
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: /withdraw <amount> [TRX/USDT]\n"
            "Example: /withdraw 50 TRX\n\n"
            "Set wallet first: /setwallet <address>"
        )
        return

    try:
        amount = float(context.args[0])
    except ValueError:
        await update.message.reply_text("Amount dapat number.")
        return

    if amount <= 0:
        await update.message.reply_text("Amount dapat positive number.")
        return

    currency = "TRX"
    if len(context.args) >= 2:
        currency = context.args[1].upper()
        if currency not in config.SUPPORTED_CURRENCIES:
            await update.message.reply_text("Supported: TRX, USDT")
            return

    if amount < config.MIN_WITHDRAWAL:
        await update.message.reply_text(
            f"Minimum withdrawal: {config.MIN_WITHDRAWAL} {currency}."
        )
        return

    user_row = await db.execute_fetchall(
        "SELECT wallet_address FROM users WHERE user_id = ?",
        (user_id,),
    )
    if not user_row:
        await update.message.reply_text("Register ka muna: /start")
        return

    wallet_address = user_row[0][0]
    if not wallet_address:
        await update.message.reply_text(
            "Set wallet address mo muna: /setwallet <TRX_address>"
        )
        return

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
            f"Lock period pa. Unlock in {days_left} day(s)."
        )
        return

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
            f"Hindi enough. Balance mo: {bal:.4f} {currency}."
        )
        return

    await db.execute(
        """INSERT INTO withdrawals (user_id, amount, fee, net_amount, currency, wallet_address, status)
           VALUES (?, ?, ?, ?, ?, ?, 'pending')""",
        (user_id, amount, fee, net, currency, wallet_address),
    )
    await db.commit()

    await update.message.reply_text(
        f"Withdrawal submitted! 🎉\n\n"
        f"Amount: {amount} {currency}\n"
        f"Fee ({config.WITHDRAWAL_FEE_PCT}%): {fee:.4f} {currency}\n"
        f"You receive: {net:.4f} {currency}\n"
        f"To: {wallet_address}\n"
        "Status: Pending"
    )


async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show withdrawal history."""
    user_id = update.effective_user.id
    db = await get_db()

    rows = await db.execute_fetchall(
        """SELECT id, amount, fee, net_amount, currency, wallet_address, status, created_at
           FROM withdrawals WHERE user_id = ?
           ORDER BY created_at DESC LIMIT 10""",
        (user_id,),
    )

    if not rows:
        await update.message.reply_text("No withdrawals yet.")
        return

    lines = ["Withdrawal History:\n"]
    for r in rows:
        wd_id, amount, fee, net, currency, wallet, status, created = r
        emoji = {"pending": "⏳", "approved": "✅", "rejected": "❌"}.get(status, "?")
        lines.append(
            f"{emoji} #{wd_id} | {net} {currency} | {status}\n"
            f"  Fee: {fee} | {created[:16]}"
        )

    await update.message.reply_text("\n".join(lines))


def register(app):
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("setwallet", setwallet))
    app.add_handler(CommandHandler("mywallet", mywallet))
    app.add_handler(CommandHandler("withdraw", withdraw))
    app.add_handler(CommandHandler("history", history))
