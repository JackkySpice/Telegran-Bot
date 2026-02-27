"""Tests for compensation plan logic."""

import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["DB_PATH"] = ":memory:"

import config
from complan import (
    calculate_profit,
    can_user_invest,
    create_investment,
    distribute_referral_commissions,
    get_plan_for_amount,
    get_referral_stats,
    get_user_portfolio,
    process_daily_earnings,
    validate_amount,
)
from database import get_db


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestCalculateProfit(unittest.TestCase):
    def test_plan1_min(self):
        r = calculate_profit(1, 50)
        self.assertAlmostEqual(r["total_profit"], 50 * 0.18, places=4)
        self.assertAlmostEqual(r["daily_profit"], 50 * 0.18 / 60, places=4)
        self.assertEqual(r["lock_days"], 40)
        self.assertEqual(r["duration_days"], 60)

    def test_plan2_max(self):
        r = calculate_profit(2, 450)
        self.assertAlmostEqual(r["total_profit"], 450 * 0.20, places=4)
        self.assertEqual(r["lock_days"], 30)

    def test_plan3(self):
        r = calculate_profit(3, 650)
        self.assertAlmostEqual(r["total_profit"], 650 * 0.22, places=4)
        self.assertEqual(r["lock_days"], 13)


class TestGetPlanForAmount(unittest.TestCase):
    def test_exact_boundaries(self):
        self.assertEqual(get_plan_for_amount(50), 1)
        self.assertEqual(get_plan_for_amount(250), 1)
        self.assertEqual(get_plan_for_amount(251), 2)
        self.assertEqual(get_plan_for_amount(450), 2)
        self.assertEqual(get_plan_for_amount(451), 3)
        self.assertEqual(get_plan_for_amount(650), 3)

    def test_out_of_range(self):
        self.assertIsNone(get_plan_for_amount(49))
        self.assertIsNone(get_plan_for_amount(651))
        self.assertIsNone(get_plan_for_amount(0))


class TestValidateAmount(unittest.TestCase):
    def test_valid(self):
        self.assertIsNone(validate_amount(1, 100))
        self.assertIsNone(validate_amount(2, 300))
        self.assertIsNone(validate_amount(3, 500))

    def test_too_low(self):
        self.assertIsNotNone(validate_amount(1, 10))

    def test_too_high(self):
        self.assertIsNotNone(validate_amount(1, 300))

    def test_invalid_plan(self):
        self.assertIsNotNone(validate_amount(99, 100))


class TestInvestmentRules(unittest.TestCase):
    def setUp(self):
        import database
        database._db = None
        os.environ["DB_PATH"] = ":memory:"

    def test_can_invest_fresh_user(self):
        async def _test():
            db = await get_db()
            await db.execute(
                "INSERT INTO users (user_id, username, referral_code) VALUES (1, 'test', 'abc')"
            )
            await db.commit()
            ok, msg = await can_user_invest(1, 1)
            self.assertTrue(ok)
            self.assertEqual(msg, "")
        run(_test())

    def test_cannot_invest_same_plan_twice(self):
        async def _test():
            db = await get_db()
            await db.execute(
                "INSERT INTO users (user_id, username, referral_code) VALUES (2, 'test2', 'def')"
            )
            await db.commit()
            await create_investment(2, 1, 100, "TRX")
            ok, msg = await can_user_invest(2, 1)
            self.assertFalse(ok)
            self.assertIn("active", msg)
        run(_test())

    def test_can_invest_different_plans(self):
        async def _test():
            db = await get_db()
            await db.execute(
                "INSERT INTO users (user_id, username, referral_code) VALUES (3, 'test3', 'ghi')"
            )
            await db.commit()
            await create_investment(3, 1, 100, "TRX")
            ok, _ = await can_user_invest(3, 2)
            self.assertTrue(ok)
        run(_test())

    def test_max_3_active_plans(self):
        async def _test():
            db = await get_db()
            await db.execute(
                "INSERT INTO users (user_id, username, referral_code) VALUES (4, 'test4', 'jkl')"
            )
            await db.commit()
            await create_investment(4, 1, 100, "TRX")
            await create_investment(4, 2, 300, "TRX")
            await create_investment(4, 3, 500, "TRX")
            ok, msg = await can_user_invest(4, 1)
            self.assertFalse(ok)
            self.assertIn("3", msg)
        run(_test())


class TestReferralCommissions(unittest.TestCase):
    def setUp(self):
        import database
        database._db = None
        os.environ["DB_PATH"] = ":memory:"

    def test_level1_commission(self):
        async def _test():
            db = await get_db()
            await db.execute(
                "INSERT INTO users (user_id, username, referral_code) VALUES (10, 'referrer', 'ref10')"
            )
            await db.execute(
                "INSERT INTO users (user_id, username, referral_code, referred_by) VALUES (11, 'investor', 'ref11', 10)"
            )
            await db.commit()

            await create_investment(11, 1, 200, "TRX")

            stats = await get_referral_stats(10)
            expected = 200 * 0.03
            self.assertAlmostEqual(stats["grand_total"], expected, places=4)

            row = await db.execute_fetchall(
                "SELECT balance_trx FROM users WHERE user_id = 10"
            )
            self.assertAlmostEqual(row[0][0], expected, places=4)
        run(_test())

    def test_multilevel_commission(self):
        async def _test():
            db = await get_db()
            await db.execute(
                "INSERT INTO users (user_id, username, referral_code) VALUES (20, 'l1', 'r20')"
            )
            await db.execute(
                "INSERT INTO users (user_id, username, referral_code, referred_by) VALUES (21, 'l2', 'r21', 20)"
            )
            await db.execute(
                "INSERT INTO users (user_id, username, referral_code, referred_by) VALUES (22, 'l3', 'r22', 21)"
            )
            await db.commit()

            await create_investment(22, 2, 300, "TRX")

            stats_l1 = await get_referral_stats(21)
            self.assertAlmostEqual(stats_l1["grand_total"], 300 * 0.03, places=4)

            stats_l2 = await get_referral_stats(20)
            self.assertAlmostEqual(stats_l2["grand_total"], 300 * 0.01, places=4)
        run(_test())


class TestDailyEarnings(unittest.TestCase):
    def setUp(self):
        import database
        database._db = None
        os.environ["DB_PATH"] = ":memory:"

    def test_daily_credit(self):
        async def _test():
            db = await get_db()
            await db.execute(
                "INSERT INTO users (user_id, username, referral_code) VALUES (30, 'daily', 'r30')"
            )
            await db.commit()

            await create_investment(30, 1, 100, "TRX")

            await process_daily_earnings()

            row = await db.execute_fetchall(
                "SELECT balance_trx FROM users WHERE user_id = 30"
            )
            daily = 100 * 0.18 / 60
            self.assertAlmostEqual(row[0][0], daily, places=4)

            inv = await db.execute_fetchall(
                "SELECT earned_so_far FROM investments WHERE user_id = 30"
            )
            self.assertAlmostEqual(inv[0][0], daily, places=4)
        run(_test())


class TestPortfolio(unittest.TestCase):
    def setUp(self):
        import database
        database._db = None
        os.environ["DB_PATH"] = ":memory:"

    def test_portfolio_returns_investments(self):
        async def _test():
            db = await get_db()
            await db.execute(
                "INSERT INTO users (user_id, username, referral_code) VALUES (40, 'port', 'r40')"
            )
            await db.commit()

            await create_investment(40, 1, 100, "TRX")
            await create_investment(40, 2, 300, "USDT")

            portfolio = await get_user_portfolio(40)
            self.assertEqual(len(portfolio), 2)
            currencies = sorted([p["currency"] for p in portfolio])
            self.assertEqual(currencies, ["TRX", "USDT"])
        run(_test())


if __name__ == "__main__":
    unittest.main()
