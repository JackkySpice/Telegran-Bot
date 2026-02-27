# Kimielbot

Telegram investment bot with CoinPayments integration, tiered compensation plans, referral commissions, and automated daily profit distribution.

## Features

- **CoinPayments Integration** for anonymous crypto deposits (TRX, USDT/TRC-20)
- **3 Tiered Investment Plans** with varying profit rates and lock periods
- **5-Level Referral System** (commissions on profit, not deposit)
- **Automated Daily Earnings** via scheduled job (00:00 UTC)
- **Weekly Withdrawals** (Sundays) with 5% fee
- **IPN Webhook Server** for automatic payment confirmations
- **Admin Dashboard** with deposit/withdrawal management, payout pause/resume
- **Offline Mode** if CoinPayments is not configured (admin confirms deposits manually)
- **No Forced Referral** for withdrawals

## Investment Plans

| Plan | Amount Range | Profit (60 days) | Withdrawal Unlock |
|------|-------------|-------------------|-------------------|
| Plan 1 | 50 - 250 TRX/USDT | 18% | After 40 days |
| Plan 2 | 251 - 450 TRX/USDT | 20% | After 30 days |
| Plan 3 | 451 - 650 TRX/USDT | 22% | After 13 days |

## Deposit Flow

1. User runs `/invest <plan> <amount> [TRX/USDT]`
2. Bot creates a CoinPayments transaction and shows a deposit address
3. User sends crypto to the address
4. CoinPayments sends IPN callback to confirm payment
5. Bot automatically activates the investment and notifies the user

If CoinPayments is not configured, deposits are created in "offline" mode and an admin confirms them manually via `/confirmdeposit <id>`.

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Configure environment:
   ```bash
   cp .env.example .env
   # Fill in: TELEGRAM_BOT_TOKEN, ADMIN_USER_IDS
   # Optional: CP_PUBLIC_KEY, CP_PRIVATE_KEY, CP_IPN_SECRET, CP_MERCHANT_ID, IPN_URL
   ```
3. Run the bot:
   ```bash
   python bot.py
   ```

## Commands

### User Commands
| Command | Description |
|---------|-------------|
| `/start` | Register |
| `/plans` | View investment plans |
| `/invest <plan> <amount> [TRX/USDT]` | Create a deposit |
| `/deposits` | Check deposit status |
| `/portfolio` | Check investment status |
| `/balance` | View balance |
| `/setwallet <address>` | Set withdrawal wallet |
| `/withdraw <amount> [TRX/USDT]` | Withdraw (Sundays only) |
| `/referral` | Referral link and stats |
| `/howitworks` | How it works |

### Admin Commands
| Command | Description |
|---------|-------------|
| `/adminstats` | Dashboard |
| `/dailyrun` | Trigger daily earnings manually |
| `/pausepayouts` | Pause all payouts |
| `/resumepayouts` | Resume payouts |
| `/pendingdeposits` | List pending deposits |
| `/confirmdeposit <id>` | Manually confirm a deposit |
| `/pending` | List pending withdrawals |
| `/approve <id>` | Approve a withdrawal |

## Architecture

```
bot.py              Main entry, scheduler, IPN server startup
config.py           Plans, referral levels, CoinPayments settings
database.py         SQLite (users, deposits, investments, referrals, withdrawals, settings)
complan.py          Profit calc, referral distribution, daily earnings engine
coinpayments.py     CoinPayments API client (HMAC auth, create_transaction, IPN verify)
ipn_server.py       aiohttp webhook server for payment confirmations
handlers/
  start.py          /start, /help
  invest.py         /plans, /invest, /deposits
  withdraw.py       /balance, /setwallet, /withdraw
  referral.py       /referral
  info.py           /howitworks, /portfolio
  admin.py          All admin commands
tests/
  test_complan.py   Unit tests for business logic
```
