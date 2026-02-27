"""Tests for compensation plan logic."""

import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["DB_PATH"] = ":memory:"

import config
from complan import (
    are_payouts_paused,
    calculate_profit,
    calculate_withdrawal_fee,
    can_user_invest,
    create_investment,
    get_plan_for_amount,
    get_referral_stats,
    get_user_portfolio,
    process_daily_earnings,
    validate_amount,
)
from database import get_db, set_setting


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


class TestWithdrawalFee(unittest.TestCase):
    def test_fee_calculation(self):
        fee, net = calculate_withdrawal_fee(100)
        self.assertAlmostEqual(fee, 5.0, places=4)
        self.assertAlmostEqual(net, 95.0, places=4)

    def test_fee_small_amount(self):
        fee, net = calculate_withdrawal_fee(30)
        self.assertAlmostEqual(fee, 1.5, places=4)
        self.assertAlmostEqual(net, 28.5, places=4)


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


class TestReferralOnProfit(unittest.TestCase):
    def setUp(self):
        import database
        database._db = None
        os.environ["DB_PATH"] = ":memory:"

    def test_no_referral_at_invest_time(self):
        async def _test():
            db = await get_db()
            await db.execute(
                "INSERT INTO users (user_id, username, referral_code) VALUES (10, 'referrer', 'ref10')"
            )
            await db.execute(
                "INSERT INTO users (user_id, username, referral_code, referred_by) VALUES (11, 'investor', 'ref11', 10)"
            )
            await db.commit()

            self.assertTrue(config.REFERRAL_ON_PROFIT)
            await create_investment(11, 1, 200, "TRX")

            stats = await get_referral_stats(10)
            self.assertAlmostEqual(stats["grand_total"], 0, places=4)
        run(_test())

    def test_referral_credited_on_daily_earnings(self):
        async def _test():
            db = await get_db()
            await db.execute(
                "INSERT INTO users (user_id, username, referral_code) VALUES (12, 'ref', 'ref12')"
            )
            await db.execute(
                "INSERT INTO users (user_id, username, referral_code, referred_by) VALUES (13, 'inv', 'ref13', 12)"
            )
            await db.commit()

            await create_investment(13, 1, 200, "TRX")
            await process_daily_earnings()

            daily_profit = 200 * 0.18 / 60
            expected_commission = daily_profit * 0.03

            stats = await get_referral_stats(12)
            self.assertAlmostEqual(stats["grand_total"], expected_commission, places=4)
        run(_test())

    def test_multilevel_on_profit(self):
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
            await process_daily_earnings()

            daily_profit = 300 * 0.20 / 60

            stats_l1 = await get_referral_stats(21)
            self.assertAlmostEqual(stats_l1["grand_total"], daily_profit * 0.03, places=4)

            stats_l2 = await get_referral_stats(20)
            self.assertAlmostEqual(stats_l2["grand_total"], daily_profit * 0.01, places=4)
        run(_test())


class TestPayoutPause(unittest.TestCase):
    def setUp(self):
        import database
        database._db = None
        os.environ["DB_PATH"] = ":memory:"

    def test_pause_blocks_earnings(self):
        async def _test():
            db = await get_db()
            await db.execute(
                "INSERT INTO users (user_id, username, referral_code) VALUES (50, 'paused', 'r50')"
            )
            await db.commit()
            await create_investment(50, 1, 100, "TRX")

            await set_setting("payouts_paused", "1")
            self.assertTrue(await are_payouts_paused())

            count = await process_daily_earnings()
            self.assertEqual(count, 0)

            row = await db.execute_fetchall(
                "SELECT balance_trx FROM users WHERE user_id = 50"
            )
            self.assertAlmostEqual(row[0][0], 0.0, places=4)
        run(_test())

    def test_resume_allows_earnings(self):
        async def _test():
            db = await get_db()
            await db.execute(
                "INSERT INTO users (user_id, username, referral_code) VALUES (51, 'resumed', 'r51')"
            )
            await db.commit()
            await create_investment(51, 1, 100, "TRX")

            await set_setting("payouts_paused", "1")
            await process_daily_earnings()

            await set_setting("payouts_paused", "0")
            self.assertFalse(await are_payouts_paused())

            count = await process_daily_earnings()
            self.assertEqual(count, 1)

            daily = 100 * 0.18 / 60
            row = await db.execute_fetchall(
                "SELECT balance_trx FROM users WHERE user_id = 51"
            )
            self.assertAlmostEqual(row[0][0], daily, places=4)
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


class TestDeposits(unittest.TestCase):
    def setUp(self):
        import database
        database._db = None
        os.environ["DB_PATH"] = ":memory:"

    def test_deposit_table_exists(self):
        async def _test():
            db = await get_db()
            await db.execute(
                "INSERT INTO users (user_id, username, referral_code) VALUES (60, 'dep', 'r60')"
            )
            await db.execute(
                """INSERT INTO deposits (user_id, plan_id, amount, currency, deposit_address, status)
                   VALUES (60, 1, 100, 'TRX', 'manual', 'pending')"""
            )
            await db.commit()

            rows = await db.execute_fetchall(
                "SELECT id, status FROM deposits WHERE user_id = 60"
            )
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][1], "pending")
        run(_test())

    def test_confirm_deposit_creates_investment(self):
        async def _test():
            db = await get_db()
            await db.execute(
                "INSERT INTO users (user_id, username, referral_code) VALUES (61, 'dep2', 'r61')"
            )
            await db.execute(
                """INSERT INTO deposits (user_id, plan_id, amount, currency, deposit_address, status)
                   VALUES (61, 2, 300, 'TRX', 'manual', 'pending')"""
            )
            await db.commit()

            dep_row = await db.execute_fetchall(
                "SELECT id FROM deposits WHERE user_id = 61"
            )
            dep_id = dep_row[0][0]

            await db.execute(
                "UPDATE deposits SET status = 'confirmed', confirmed_at = datetime('now') WHERE id = ?",
                (dep_id,),
            )
            await db.commit()

            result = await create_investment(61, 2, 300, "TRX")

            await db.execute(
                "UPDATE investments SET deposit_id = ? WHERE id = ?",
                (dep_id, result["investment_id"]),
            )
            await db.commit()

            inv = await db.execute_fetchall(
                "SELECT deposit_id, amount, plan_id FROM investments WHERE user_id = 61"
            )
            self.assertEqual(len(inv), 1)
            self.assertEqual(inv[0][0], dep_id)
            self.assertAlmostEqual(inv[0][1], 300.0)
            self.assertEqual(inv[0][2], 2)
        run(_test())

    def test_pending_deposit_blocks_duplicate(self):
        async def _test():
            db = await get_db()
            await db.execute(
                "INSERT INTO users (user_id, username, referral_code) VALUES (62, 'dup', 'r62')"
            )
            await db.execute(
                """INSERT INTO deposits (user_id, plan_id, amount, currency, deposit_address, status)
                   VALUES (62, 1, 100, 'TRX', 'manual', 'pending')"""
            )
            await db.commit()

            pending = await db.execute_fetchall(
                "SELECT id FROM deposits WHERE user_id = 62 AND plan_id = 1 AND status = 'pending'"
            )
            self.assertTrue(len(pending) > 0)
        run(_test())


class TestCoinPaymentsClient(unittest.TestCase):
    def test_ipn_verify(self):
        import hashlib
        import hmac
        from coinpayments import verify_ipn

        secret = "test_secret"
        config.CP_IPN_SECRET = secret

        body = b"test_body_data"
        expected_hmac = hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()

        self.assertTrue(verify_ipn(expected_hmac, body))
        self.assertFalse(verify_ipn("wrong_hmac", body))

        config.CP_IPN_SECRET = ""

    def test_coin_map(self):
        from coinpayments import COIN_MAP
        self.assertEqual(COIN_MAP["TRX"], "TRX")
        self.assertEqual(COIN_MAP["USDT"], "USDT.TRC20")


class TestWalletAddress(unittest.TestCase):
    def setUp(self):
        import database
        database._db = None
        os.environ["DB_PATH"] = ":memory:"

    def test_set_wallet_address(self):
        async def _test():
            db = await get_db()
            await db.execute(
                "INSERT INTO users (user_id, username, referral_code) VALUES (70, 'wallet', 'r70')"
            )
            await db.commit()

            await db.execute(
                "UPDATE users SET wallet_address = ? WHERE user_id = ?",
                ("TXyz123abc456def789", 70),
            )
            await db.commit()

            row = await db.execute_fetchall(
                "SELECT wallet_address FROM users WHERE user_id = 70"
            )
            self.assertEqual(row[0][0], "TXyz123abc456def789")
        run(_test())

    def test_wallet_default_null(self):
        async def _test():
            db = await get_db()
            await db.execute(
                "INSERT INTO users (user_id, username, referral_code) VALUES (71, 'nowallet', 'r71')"
            )
            await db.commit()

            row = await db.execute_fetchall(
                "SELECT wallet_address FROM users WHERE user_id = 71"
            )
            self.assertIsNone(row[0][0])
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
