"""Admin commands for managing the platform."""

from __future__ import annotations

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

import config
from complan import are_payouts_paused, process_daily_earnings
from database import get_db, get_setting, set_setting


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
    paused = await are_payouts_paused()

    split = config.PROFIT_SPLIT
    await update.message.reply_text(
        "Admin Dashboard:\n\n"
        f"Users: {user_count}\n"
        f"Active investments: {active_inv[0]} ({active_inv[1]:.2f})\n"
        f"Pending withdrawals: {pending_wd[0]} ({pending_wd[1]:.2f})\n"
        f"Referral payouts: {total_ref:.2f}\n"
        f"Payouts paused: {'YES' if paused else 'NO'}\n\n"
        f"Profit split: {split['users']}% users / "
        f"{split['reserve']}% reserve / {split['team']}% team"
    )


async def trigger_daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return

    count = await process_daily_earnings()
    if count == 0 and await are_payouts_paused():
        await update.message.reply_text("Payouts paused. /resumepayouts muna.")
    else:
        await update.message.reply_text(f"Done! {count} investments credited. ✅")


async def pause_payouts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    await set_setting("payouts_paused", "1")
    await update.message.reply_text("Payouts paused. Walang crediting hanggang i-resume.")


async def resume_payouts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    await set_setting("payouts_paused", "0")
    await update.message.reply_text("Payouts resumed! ✅")


async def approve_withdrawal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text("Usage: /approve <withdrawal_id>")
        return

    try:
        wd_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID dapat number.")
        return

    db = await get_db()
    row = await db.execute_fetchall(
        "SELECT id, user_id, amount, fee, net_amount, currency, status FROM withdrawals WHERE id = ?",
        (wd_id,),
    )
    if not row:
        await update.message.reply_text("Not found.")
        return

    if row[0][6] != "pending":
        await update.message.reply_text(f"Status: {row[0][6]}. Hindi pending.")
        return

    await db.execute(
        "UPDATE withdrawals SET status = 'approved', processed_at = datetime('now') WHERE id = ?",
        (wd_id,),
    )
    await db.commit()

    await update.message.reply_text(
        f"Withdrawal #{wd_id} approved!\n"
        f"User: {row[0][1]}\n"
        f"Gross: {row[0][2]} {row[0][5]}\n"
        f"Fee: {row[0][3]} | Net: {row[0][4]}"
    )


async def list_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return

    db = await get_db()
    rows = await db.execute_fetchall(
        """SELECT w.id, w.user_id, u.username, w.amount, w.fee, w.net_amount, w.currency, w.created_at
           FROM withdrawals w JOIN users u ON w.user_id = u.user_id
           WHERE w.status = 'pending' ORDER BY w.created_at ASC"""
    )
    if not rows:
        await update.message.reply_text("No pending withdrawals.")
        return

    lines = ["Pending Withdrawals:\n"]
    for r in rows:
        lines.append(
            f"#{r[0]} | @{r[2] or r[1]} | {r[3]} {r[6]} (fee:{r[4]}, net:{r[5]})"
        )
    lines.append(f"\nTotal: {len(rows)}")
    lines.append("/approve <id>")

    await update.message.reply_text("\n".join(lines))


def register(app):
    app.add_handler(CommandHandler("adminstats", admin_stats))
    app.add_handler(CommandHandler("dailyrun", trigger_daily))
    app.add_handler(CommandHandler("pausepayouts", pause_payouts))
    app.add_handler(CommandHandler("resumepayouts", resume_payouts))
    app.add_handler(CommandHandler("approve", approve_withdrawal))
    app.add_handler(CommandHandler("pending", list_pending))
