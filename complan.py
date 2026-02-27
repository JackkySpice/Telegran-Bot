"""Compensation plan engine.

Handles profit calculation, referral commission distribution,
and plan validation rules.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import config
from database import get_db


def calculate_profit(plan_id: int, amount: float) -> dict:
    """Return daily profit, total profit, unlock date, and expiry for a given plan + amount."""
    plan = config.PLANS[plan_id]
    total_profit = amount * (plan["profit_pct"] / 100.0)
    daily_profit = total_profit / plan["duration_days"]
    now = datetime.now(timezone.utc)
    unlocks_at = now + timedelta(days=plan["lock_days"])
    expires_at = now + timedelta(days=plan["duration_days"])

    return {
        "plan_id": plan_id,
        "amount": amount,
        "profit_pct": plan["profit_pct"],
        "duration_days": plan["duration_days"],
        "lock_days": plan["lock_days"],
        "daily_profit": round(daily_profit, 6),
        "total_profit": round(total_profit, 6),
        "unlocks_at": unlocks_at.isoformat(),
        "expires_at": expires_at.isoformat(),
    }


def get_plan_for_amount(amount: float) -> int | None:
    """Return the plan_id that matches the given amount, or None."""
    for pid, plan in config.PLANS.items():
        if plan["min_amount"] <= amount <= plan["max_amount"]:
            return pid
    return None


def validate_amount(plan_id: int, amount: float) -> str | None:
    """Return an error message if the amount is invalid for the plan, else None."""
    plan = config.PLANS.get(plan_id)
    if plan is None:
        return "Invalid plan."
    if amount < plan["min_amount"] or amount > plan["max_amount"]:
        return (
            f"Amount must be between {plan['min_amount']} and {plan['max_amount']} "
            f"for {plan['name']}."
        )
    return None


async def can_user_invest(user_id: int, plan_id: int) -> tuple[bool, str]:
    """Check plan rules: max 3 active plans, only 1 active per plan_id."""
    db = await get_db()

    active = await db.execute_fetchall(
        "SELECT plan_id FROM investments WHERE user_id = ? AND status = 'active'",
        (user_id,),
    )

    active_plan_ids = [row[0] for row in active]

    if len(active_plan_ids) >= config.MAX_ACTIVE_PLANS_PER_USER:
        return False, "May 3 active plans ka na. Hintayin mo muna matapos ang isa."

    if plan_id in active_plan_ids:
        return False, (
            f"May active {config.PLANS[plan_id]['name']} ka pa. "
            "Hindi pwede ulitin hanggang di pa tapos ang 60 days."
        )

    return True, ""


async def create_investment(user_id: int, plan_id: int, amount: float, currency: str = "TRX") -> dict:
    """Create an investment record and distribute referral commissions."""
    db = await get_db()
    details = calculate_profit(plan_id, amount)

    await db.execute(
        """INSERT INTO investments
           (user_id, plan_id, amount, currency, profit_pct, duration_days,
            lock_days, daily_profit, total_profit, unlocks_at, expires_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            user_id,
            plan_id,
            amount,
            currency,
            details["profit_pct"],
            details["duration_days"],
            details["lock_days"],
            details["daily_profit"],
            details["total_profit"],
            details["unlocks_at"],
            details["expires_at"],
        ),
    )
    await db.commit()

    row = await db.execute_fetchall(
        "SELECT last_insert_rowid()"
    )
    investment_id = row[0][0]

    await distribute_referral_commissions(user_id, investment_id, amount, currency)

    return {**details, "investment_id": investment_id, "currency": currency}


async def distribute_referral_commissions(
    investor_id: int,
    investment_id: int,
    amount: float,
    currency: str,
):
    """Walk upline up to 5 levels and credit referral commissions."""
    db = await get_db()
    current_id = investor_id

    for level in range(1, len(config.REFERRAL_LEVELS) + 1):
        row = await db.execute_fetchall(
            "SELECT referred_by FROM users WHERE user_id = ?",
            (current_id,),
        )
        if not row or row[0][0] is None:
            break

        referrer_id = row[0][0]
        pct = config.REFERRAL_LEVELS[level]
        commission = round(amount * (pct / 100.0), 6)

        await db.execute(
            """INSERT INTO referral_earnings
               (user_id, from_user_id, investment_id, level, pct, amount, currency)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (referrer_id, investor_id, investment_id, level, pct, commission, currency),
        )

        balance_col = "balance_trx" if currency == "TRX" else "balance_usdt"
        await db.execute(
            f"UPDATE users SET {balance_col} = {balance_col} + ? WHERE user_id = ?",
            (commission, referrer_id),
        )

        current_id = referrer_id

    await db.commit()


async def process_daily_earnings():
    """Credit daily profit to users with active investments (call via scheduler)."""
    db = await get_db()
    now = datetime.now(timezone.utc).isoformat()

    rows = await db.execute_fetchall(
        """SELECT id, user_id, daily_profit, earned_so_far, total_profit, currency
           FROM investments
           WHERE status = 'active' AND expires_at > ?""",
        (now,),
    )

    for row in rows:
        inv_id, user_id, daily_profit, earned, total, currency = row
        new_earned = min(earned + daily_profit, total)
        credit = new_earned - earned

        if credit <= 0:
            continue

        balance_col = "balance_trx" if currency == "TRX" else "balance_usdt"
        await db.execute(
            f"UPDATE users SET {balance_col} = {balance_col} + ? WHERE user_id = ?",
            (credit, user_id),
        )
        await db.execute(
            "UPDATE investments SET earned_so_far = ? WHERE id = ?",
            (new_earned, inv_id),
        )

        if new_earned >= total:
            await db.execute(
                "UPDATE investments SET status = 'completed' WHERE id = ?",
                (inv_id,),
            )

    await db.commit()


async def get_user_portfolio(user_id: int) -> list[dict]:
    """Return all investments for a user."""
    db = await get_db()
    rows = await db.execute_fetchall(
        """SELECT id, plan_id, amount, currency, profit_pct, daily_profit,
                  total_profit, earned_so_far, status, started_at, unlocks_at, expires_at
           FROM investments WHERE user_id = ? ORDER BY started_at DESC""",
        (user_id,),
    )
    return [
        {
            "id": r[0], "plan_id": r[1], "amount": r[2], "currency": r[3],
            "profit_pct": r[4], "daily_profit": r[5], "total_profit": r[6],
            "earned_so_far": r[7], "status": r[8], "started_at": r[9],
            "unlocks_at": r[10], "expires_at": r[11],
        }
        for r in rows
    ]


async def get_referral_stats(user_id: int) -> dict:
    """Return referral earning totals per level and overall."""
    db = await get_db()
    rows = await db.execute_fetchall(
        """SELECT level, SUM(amount) as total, COUNT(*) as count
           FROM referral_earnings WHERE user_id = ?
           GROUP BY level ORDER BY level""",
        (user_id,),
    )
    levels = {r[0]: {"total": r[1], "count": r[2]} for r in rows}
    grand_total = sum(v["total"] for v in levels.values())
    return {"levels": levels, "grand_total": grand_total}
