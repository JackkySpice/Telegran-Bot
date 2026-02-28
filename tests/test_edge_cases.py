"""Edge case and validation tests."""

import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["DB_PATH"] = ":memory:"

import config
from complan import (
    calculate_profit,
    calculate_withdrawal_fee,
    can_user_invest,
    create_investment,
    get_referral_stats,
    get_user_portfolio,
    process_daily_earnings,
    validate_amount,
)
from database import get_db


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestNegativeAndZeroAmounts(unittest.TestCase):
    def test_negative_amount_rejected(self):
        err = validate_amount(1, -50)
        self.assertIsNotNone(err)

    def test_zero_amount_rejected(self):
        err = validate_amount(1, 0)
        self.assertIsNotNone(err)

    def test_zero_withdrawal_fee(self):
        fee, net = calculate_withdrawal_fee(0)
        self.assertEqual(fee, 0)
        self.assertEqual(net, 0)

    def test_very_large_amount(self):
        err = validate_amount(3, 999999)
        self.assertIsNotNone(err)


class TestUnregisteredUser(unittest.TestCase):
    def setUp(self):
        import database
        database._db = None

    def test_create_investment_fails_for_unregistered(self):
        async def _test():
            await get_db()
            with self.assertRaises(Exception):
                await create_investment(999999, 1, 100, "TRX")
        run(_test())


class TestInvestmentCompletion(unittest.TestCase):
    def setUp(self):
        import database
        database._db = None

    def test_investment_completes_after_full_earnings(self):
        async def _test():
            db = await get_db()
            await db.execute(
                "INSERT INTO users (user_id, username, referral_code) VALUES (100, 'full', 'r100')"
            )
            await db.commit()
            await create_investment(100, 1, 100, "TRX")

            for _ in range(61):
                await process_daily_earnings()

            inv = await db.execute_fetchall(
                "SELECT status, earned_so_far, total_profit FROM investments WHERE user_id = 100"
            )
            self.assertEqual(inv[0][0], "completed")
            self.assertAlmostEqual(inv[0][1], inv[0][2], places=4)
        run(_test())

    def test_no_double_credit_after_completion(self):
        async def _test():
            db = await get_db()
            await db.execute(
                "INSERT INTO users (user_id, username, referral_code) VALUES (101, 'done', 'r101')"
            )
            await db.commit()
            await create_investment(101, 1, 100, "TRX")

            for _ in range(61):
                await process_daily_earnings()

            bal_before = (await db.execute_fetchall(
                "SELECT balance_trx FROM users WHERE user_id = 101"
            ))[0][0]

            await process_daily_earnings()

            bal_after = (await db.execute_fetchall(
                "SELECT balance_trx FROM users WHERE user_id = 101"
            ))[0][0]

            self.assertAlmostEqual(bal_before, bal_after, places=6)
        run(_test())


class TestReinvestAfterCompletion(unittest.TestCase):
    def setUp(self):
        import database
        database._db = None

    def test_can_reinvest_after_plan_completes(self):
        async def _test():
            db = await get_db()
            await db.execute(
                "INSERT INTO users (user_id, username, referral_code) VALUES (110, 're', 'r110')"
            )
            await db.commit()
            await create_investment(110, 1, 100, "TRX")

            await db.execute(
                "UPDATE investments SET status = 'completed' WHERE user_id = 110"
            )
            await db.commit()

            ok, msg = await can_user_invest(110, 1)
            self.assertTrue(ok, f"Should allow reinvest after completion: {msg}")
        run(_test())


class TestTimezoneHandling(unittest.TestCase):
    def test_isoformat_roundtrip(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        iso = now.isoformat()
        parsed = datetime.fromisoformat(iso)
        self.assertIsNotNone(parsed.tzinfo)
        diff = abs((parsed - now).total_seconds())
        self.assertLess(diff, 1)

    def test_profit_dates_are_tz_aware(self):
        from datetime import datetime, timezone
        r = calculate_profit(1, 100)
        parsed_unlock = datetime.fromisoformat(r["unlocks_at"])
        parsed_expiry = datetime.fromisoformat(r["expires_at"])
        self.assertIsNotNone(parsed_unlock.tzinfo)
        self.assertIsNotNone(parsed_expiry.tzinfo)
        self.assertGreater(parsed_expiry, parsed_unlock)


class TestCoinPaymentsVerify(unittest.TestCase):
    def test_verify_valid_hmac(self):
        import hashlib
        import hmac as hmac_mod
        from coinpayments import verify_ipn

        config.CP_IPN_SECRET = "test_secret_123"
        body = b"txn_id=abc123&status=100&amount1=100"
        expected = hmac_mod.new(b"test_secret_123", body, hashlib.sha512).hexdigest()
        self.assertTrue(verify_ipn(expected, body))
        config.CP_IPN_SECRET = ""

    def test_reject_invalid_hmac(self):
        from coinpayments import verify_ipn
        config.CP_IPN_SECRET = "test_secret_123"
        self.assertFalse(verify_ipn("totally_wrong", b"some body"))
        config.CP_IPN_SECRET = ""

    def test_reject_tampered_body(self):
        import hashlib
        import hmac as hmac_mod
        from coinpayments import verify_ipn

        config.CP_IPN_SECRET = "secret"
        body_original = b"amount=100"
        body_tampered = b"amount=999"
        sig = hmac_mod.new(b"secret", body_original, hashlib.sha512).hexdigest()
        self.assertFalse(verify_ipn(sig, body_tampered))
        config.CP_IPN_SECRET = ""


class TestDepositFlow(unittest.TestCase):
    def setUp(self):
        import database
        database._db = None

    def test_full_deposit_to_investment_flow(self):
        async def _test():
            db = await get_db()
            await db.execute(
                "INSERT INTO users (user_id, username, referral_code) VALUES (200, 'dep', 'r200')"
            )
            await db.commit()

            await db.execute(
                """INSERT INTO deposits
                   (user_id, plan_id, amount, currency, cp_txn_id, deposit_address, status)
                   VALUES (200, 1, 150, 'TRX', 'txn_abc', 'TAddr123', 'pending')"""
            )
            await db.commit()

            dep = await db.execute_fetchall(
                "SELECT id, status FROM deposits WHERE user_id = 200"
            )
            self.assertEqual(dep[0][1], "pending")

            dep_id = dep[0][0]
            await db.execute(
                "UPDATE deposits SET status = 'confirmed', confirmed_at = datetime('now') WHERE id = ?",
                (dep_id,),
            )
            await db.commit()

            result = await create_investment(200, 1, 150, "TRX")
            await db.execute(
                "UPDATE investments SET deposit_id = ? WHERE id = ?",
                (dep_id, result["investment_id"]),
            )
            await db.commit()

            inv = await db.execute_fetchall(
                "SELECT deposit_id, amount, status FROM investments WHERE user_id = 200"
            )
            self.assertEqual(inv[0][0], dep_id)
            self.assertAlmostEqual(inv[0][1], 150.0)
            self.assertEqual(inv[0][2], "active")

            dep_final = await db.execute_fetchall(
                "SELECT status FROM deposits WHERE id = ?", (dep_id,)
            )
            self.assertEqual(dep_final[0][0], "confirmed")
        run(_test())

    def test_expired_deposit_does_not_create_investment(self):
        async def _test():
            db = await get_db()
            await db.execute(
                "INSERT INTO users (user_id, username, referral_code) VALUES (201, 'exp', 'r201')"
            )
            await db.execute(
                """INSERT INTO deposits
                   (user_id, plan_id, amount, currency, deposit_address, status)
                   VALUES (201, 1, 100, 'TRX', 'manual', 'expired')"""
            )
            await db.commit()

            inv = await db.execute_fetchall(
                "SELECT id FROM investments WHERE user_id = 201"
            )
            self.assertEqual(len(inv), 0)
        run(_test())


class TestWalletAddressOnWithdrawal(unittest.TestCase):
    def setUp(self):
        import database
        database._db = None

    def test_withdrawal_stores_wallet_address(self):
        async def _test():
            db = await get_db()
            await db.execute(
                "INSERT INTO users (user_id, username, referral_code, wallet_address, balance_trx) "
                "VALUES (300, 'wd', 'r300', 'TWallet123abc', 100.0)"
            )
            await db.commit()

            fee, net = calculate_withdrawal_fee(50)
            await db.execute(
                """INSERT INTO withdrawals
                   (user_id, amount, fee, net_amount, currency, wallet_address, status)
                   VALUES (300, 50, ?, ?, 'TRX', 'TWallet123abc', 'pending')""",
                (fee, net),
            )
            await db.commit()

            wd = await db.execute_fetchall(
                "SELECT wallet_address, fee, net_amount FROM withdrawals WHERE user_id = 300"
            )
            self.assertEqual(wd[0][0], "TWallet123abc")
            self.assertAlmostEqual(wd[0][1], 2.5, places=4)
            self.assertAlmostEqual(wd[0][2], 47.5, places=4)
        run(_test())


class TestReferralOnDeposit(unittest.TestCase):
    """Test the REFERRAL_ON_PROFIT=False path (deposit-based referrals)."""

    def setUp(self):
        import database
        database._db = None
        self._orig = config.REFERRAL_ON_PROFIT

    def tearDown(self):
        config.REFERRAL_ON_PROFIT = self._orig

    def test_deposit_based_referral(self):
        async def _test():
            config.REFERRAL_ON_PROFIT = False

            db = await get_db()
            await db.execute(
                "INSERT INTO users (user_id, username, referral_code) VALUES (400, 'ref', 'r400')"
            )
            await db.execute(
                "INSERT INTO users (user_id, username, referral_code, referred_by) "
                "VALUES (401, 'inv', 'r401', 400)"
            )
            await db.commit()

            await create_investment(401, 1, 200, "TRX")

            stats = await get_referral_stats(400)
            expected = 200 * 0.03
            self.assertAlmostEqual(stats["grand_total"], expected, places=4)

            bal = await db.execute_fetchall(
                "SELECT balance_trx FROM users WHERE user_id = 400"
            )
            self.assertAlmostEqual(bal[0][0], expected, places=4)
        run(_test())


class TestMultipleCurrencyBalance(unittest.TestCase):
    def setUp(self):
        import database
        database._db = None

    def test_trx_and_usdt_tracked_separately(self):
        async def _test():
            db = await get_db()
            await db.execute(
                "INSERT INTO users (user_id, username, referral_code) VALUES (500, 'multi', 'r500')"
            )
            await db.commit()

            await create_investment(500, 1, 100, "TRX")
            await create_investment(500, 2, 300, "USDT")

            await process_daily_earnings()

            bal = await db.execute_fetchall(
                "SELECT balance_trx, balance_usdt FROM users WHERE user_id = 500"
            )
            trx_daily = 100 * 0.18 / 60
            usdt_daily = 300 * 0.20 / 60

            self.assertAlmostEqual(bal[0][0], trx_daily, places=4)
            self.assertAlmostEqual(bal[0][1], usdt_daily, places=4)
        run(_test())


if __name__ == "__main__":
    unittest.main()
