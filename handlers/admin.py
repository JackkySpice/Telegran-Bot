"""Admin commands for managing the platform."""

from __future__ import annotations

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

import config
from complan import process_daily_earnings
from database import get_db


def _is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_USER_IDS


async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return

    db = await get_db()

    user_count = (await db.execute_fetchall("SELECT COUNT(*) FROM users"))[0][0]
    active_inv = (
        await db.execute_fetchall(
            "SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM investments WHERE status = 'active'"
        )
    )[0]
    pending_wd = (
        await db.execute_fetchall(
            "SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM withdrawals WHERE status = 'pending'"
        )
    )[0]
    total_ref = (
        await db.execute_fetchall(
            "SELECT COALESCE(SUM(amount), 0) FROM referral_earnings"
        )
    )[0][0]

    text = (
        "Admin Dashboard:\n\n"
        f"Total users: {user_count}\n"
        f"Active investments: {active_inv[0]} ({active_inv[1]:.2f} TRX/USDT)\n"
        f"Pending withdrawals: {pending_wd[0]} ({pending_wd[1]:.2f} TRX/USDT)\n"
        f"Total referral payouts: {total_ref:.2f}\n"
    )
    await update.message.reply_text(text)


async def trigger_daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually trigger daily earnings processing."""
    if not _is_admin(update.effective_user.id):
        return

    await process_daily_earnings()
    await update.message.reply_text("Daily earnings processed! ✅")


async def approve_withdrawal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Approve a pending withdrawal: /approve <withdrawal_id>"""
    if not _is_admin(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text("Usage: /approve <withdrawal_id>")
        return

    try:
        wd_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Withdrawal ID dapat number.")
        return

    db = await get_db()
    row = await db.execute_fetchall(
        "SELECT id, user_id, amount, currency, status FROM withdrawals WHERE id = ?",
        (wd_id,),
    )
    if not row:
        await update.message.reply_text("Withdrawal not found.")
        return

    if row[0][4] != "pending":
        await update.message.reply_text(f"Withdrawal status: {row[0][4]}. Hindi pending.")
        return

    await db.execute(
        "UPDATE withdrawals SET status = 'approved', processed_at = datetime('now') WHERE id = ?",
        (wd_id,),
    )
    await db.commit()

    await update.message.reply_text(
        f"Withdrawal #{wd_id} approved!\n"
        f"User: {row[0][1]}\n"
        f"Amount: {row[0][2]} {row[0][3]}"
    )


async def list_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List pending withdrawals."""
    if not _is_admin(update.effective_user.id):
        return

    db = await get_db()
    rows = await db.execute_fetchall(
        """SELECT w.id, w.user_id, u.username, w.amount, w.currency, w.created_at
           FROM withdrawals w JOIN users u ON w.user_id = u.user_id
           WHERE w.status = 'pending' ORDER BY w.created_at ASC"""
    )
    if not rows:
        await update.message.reply_text("No pending withdrawals.")
        return

    lines = ["Pending Withdrawals:\n"]
    for r in rows:
        lines.append(
            f"#{r[0]} | @{r[2] or r[1]} | {r[3]} {r[4]} | {r[5]}"
        )
    lines.append(f"\nTotal: {len(rows)} pending")
    lines.append("Approve: /approve <id>")

    await update.message.reply_text("\n".join(lines))


def register(app):
    app.add_handler(CommandHandler("adminstats", admin_stats))
    app.add_handler(CommandHandler("dailyrun", trigger_daily))
    app.add_handler(CommandHandler("approve", approve_withdrawal))
    app.add_handler(CommandHandler("pending", list_pending))
