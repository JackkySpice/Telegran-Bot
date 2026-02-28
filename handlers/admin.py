"""Admin commands for managing the platform."""

from __future__ import annotations

import html
import logging

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

import config
from complan import are_payouts_paused, create_investment, process_daily_earnings
from database import get_db, get_setting, set_setting

logger = logging.getLogger(__name__)


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
    pending_dep = (
        await db.execute_fetchall(
            "SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM deposits WHERE status = 'pending'"
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
    cp_status = "configured" if config.CP_PUBLIC_KEY else "offline"
    payout_label = "🔴 PAUSED" if paused else "🟢 ACTIVE"

    await update.message.reply_text(
        "<b>📊 Admin Dashboard</b>\n\n"
        f"Users: <code>{user_count}</code>\n"
        f"Active investments: <code>{active_inv[0]}</code> (<code>{active_inv[1]:.2f}</code>)\n"
        f"Pending deposits: <code>{pending_dep[0]}</code> (<code>{pending_dep[1]:.2f}</code>)\n"
        f"Pending withdrawals: <code>{pending_wd[0]}</code> (<code>{pending_wd[1]:.2f}</code>)\n"
        f"Referral payouts: <code>{total_ref:.2f}</code>\n"
        f"Payouts: {payout_label}\n"
        f"CoinPayments: <code>{cp_status}</code>\n\n"
        f"<i>Profit split: {split['users']}% users / "
        f"{split['reserve']}% reserve / {split['team']}% team</i>",
        parse_mode="HTML",
    )


async def trigger_daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually trigger daily earnings. Use /dailyrun force to bypass once-per-day guard."""
    if not _is_admin(update.effective_user.id):
        return

    force = bool(context.args and context.args[0].lower() == "force")
    count = await process_daily_earnings(force=force)

    if count == -1:
        await update.message.reply_text(
            "⚠️ Already ran today. Use <code>/dailyrun force</code> to override.",
            parse_mode="HTML",
        )
    elif count == 0 and await are_payouts_paused():
        await update.message.reply_text(
            "⚠️ Payouts are paused. Run <code>/resumepayouts</code> first.",
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text(
            f"✅ Done! <b>{count}</b> investments credited.",
            parse_mode="HTML",
        )


async def pause_payouts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    await set_setting("payouts_paused", "1")
    await update.message.reply_text(
        "🔴 <b>Payouts paused.</b>\nNo earnings will be credited until resumed.",
        parse_mode="HTML",
    )


async def resume_payouts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    await set_setting("payouts_paused", "0")
    await update.message.reply_text(
        "🟢 <b>Payouts resumed!</b>",
        parse_mode="HTML",
    )


async def confirm_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually confirm a deposit (offline mode): /confirmdeposit <deposit_id>"""
    if not _is_admin(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: <code>/confirmdeposit &lt;deposit_id&gt;</code>",
            parse_mode="HTML",
        )
        return

    try:
        dep_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("⚠️ ID must be a number.")
        return

    db = await get_db()
    row = await db.execute_fetchall(
        "SELECT id, user_id, plan_id, amount, currency, status FROM deposits WHERE id = ?",
        (dep_id,),
    )
    if not row:
        await update.message.reply_text("⚠️ Deposit not found.")
        return

    dep = row[0]
    if dep[5] != "pending":
        await update.message.reply_text(
            f"⚠️ Deposit status: <b>{html.escape(dep[5])}</b>. Not pending.",
            parse_mode="HTML",
        )
        return

    await db.execute(
        "UPDATE deposits SET status = 'confirmed', confirmed_at = datetime('now') WHERE id = ?",
        (dep_id,),
    )
    await db.commit()

    result = await create_investment(dep[1], dep[2], dep[3], dep[4])

    await db.execute(
        "UPDATE investments SET deposit_id = ? WHERE id = ?",
        (dep_id, result["investment_id"]),
    )
    await db.commit()

    await update.message.reply_text(
        f"✅ <b>Deposit #{dep_id} confirmed!</b>\n\n"
        f"User: <code>{dep[1]}</code>\n"
        f"Investment: <code>#{result['investment_id']}</code>\n"
        f"Plan {dep[2]} | <code>{dep[3]} {dep[4]}</code>",
        parse_mode="HTML",
    )

    try:
        plan = config.PLANS[dep[2]]
        await context.bot.send_message(
            chat_id=dep[1],
            text=(
                f"<b>✅ Payment Confirmed!</b>\n\n"
                f"<b>{plan['name']}</b> | <code>{dep[3]} {dep[4]}</code>\n"
                f"Profit: <code>{plan['profit_pct']}%</code> in <code>{plan['duration_days']}</code> days\n\n"
                "Your investment is now active.\n"
                "Tap 📈 <b>Portfolio</b> to view it."
            ),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error("Failed to notify user: %s", e)


async def list_pending_deposits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List pending deposits."""
    if not _is_admin(update.effective_user.id):
        return

    db = await get_db()
    rows = await db.execute_fetchall(
        """SELECT d.id, d.user_id, u.username, d.plan_id, d.amount, d.currency,
                  d.deposit_address, d.created_at
           FROM deposits d JOIN users u ON d.user_id = u.user_id
           WHERE d.status = 'pending' ORDER BY d.created_at ASC"""
    )
    if not rows:
        await update.message.reply_text("<i>No pending deposits.</i>", parse_mode="HTML")
        return

    lines = ["<b>⏳ Pending Deposits</b>\n"]
    for r in rows:
        uname = f"@{html.escape(r[2])}" if r[2] else str(r[1])
        lines.append(
            f"<code>#{r[0]}</code> | {uname} | Plan {r[3]} | <code>{r[4]} {r[5]}</code> | {r[7][:16]}"
        )
    lines.append(f"\nTotal: <b>{len(rows)}</b>")
    lines.append("\n<code>/confirmdeposit &lt;id&gt;</code>")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def approve_withdrawal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: <code>/approve &lt;withdrawal_id&gt;</code>",
            parse_mode="HTML",
        )
        return

    try:
        wd_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("⚠️ ID must be a number.")
        return

    db = await get_db()
    row = await db.execute_fetchall(
        "SELECT id, user_id, amount, fee, net_amount, currency, wallet_address, status FROM withdrawals WHERE id = ?",
        (wd_id,),
    )
    if not row:
        await update.message.reply_text("⚠️ Not found.")
        return

    if row[0][7] != "pending":
        await update.message.reply_text(
            f"⚠️ Status: <b>{html.escape(row[0][7])}</b>. Not pending.",
            parse_mode="HTML",
        )
        return

    await db.execute(
        "UPDATE withdrawals SET status = 'approved', processed_at = datetime('now') WHERE id = ?",
        (wd_id,),
    )
    await db.commit()

    wallet = html.escape(row[0][6]) if row[0][6] else "not set"
    await update.message.reply_text(
        f"✅ <b>Withdrawal #{wd_id} approved!</b>\n\n"
        f"User: <code>{row[0][1]}</code>\n"
        f"Net: <code>{row[0][4]} {row[0][5]}</code>\n"
        f"Wallet: <code>{wallet}</code>",
        parse_mode="HTML",
    )


async def list_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return

    db = await get_db()
    rows = await db.execute_fetchall(
        """SELECT w.id, w.user_id, u.username, w.amount, w.fee, w.net_amount,
                  w.currency, w.wallet_address, w.created_at
           FROM withdrawals w JOIN users u ON w.user_id = u.user_id
           WHERE w.status = 'pending' ORDER BY w.created_at ASC"""
    )
    if not rows:
        await update.message.reply_text(
            "<i>No pending withdrawals.</i>", parse_mode="HTML"
        )
        return

    lines = ["<b>⏳ Pending Withdrawals</b>\n"]
    for r in rows:
        uname = f"@{html.escape(r[2])}" if r[2] else str(r[1])
        wallet = html.escape(r[7]) if r[7] else "no wallet"
        lines.append(
            f"<code>#{r[0]}</code> | {uname} | <code>{r[5]} {r[6]}</code> | <code>{wallet}</code>"
        )
    lines.append(f"\nTotal: <b>{len(rows)}</b>")
    lines.append("\n<code>/approve &lt;id&gt;</code>")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


def register(app):
    app.add_handler(CommandHandler("adminstats", admin_stats))
    app.add_handler(CommandHandler("dailyrun", trigger_daily))
    app.add_handler(CommandHandler("pausepayouts", pause_payouts))
    app.add_handler(CommandHandler("resumepayouts", resume_payouts))
    app.add_handler(CommandHandler("confirmdeposit", confirm_deposit))
    app.add_handler(CommandHandler("pendingdeposits", list_pending_deposits))
    app.add_handler(CommandHandler("approve", approve_withdrawal))
    app.add_handler(CommandHandler("pending", list_pending))
