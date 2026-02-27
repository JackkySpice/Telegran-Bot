# Kimielbot

Telegram bot for an automated investment platform with tiered compensation plans, referral commissions, and weekly profit distribution.

## Features

- **3 Tiered Investment Plans** with varying profit rates and lock periods
- **5-Level Referral System** with commissions based on profit (not deposit)
- **Weekly Payout Engine** (every Sunday) with admin pause/resume
- **5% Withdrawal Fee** applied automatically
- **Profit Split** (70% users / 20% reserve / 10% team)
- **TRX & USDT Support**
- **No Forced Referral** for withdrawals
- **Admin Dashboard** with payout controls

## Investment Plans

| Plan | Amount Range | Profit (60 days) | Withdrawal Unlock |
|------|-------------|-------------------|-------------------|
| Plan 1 | 50 - 250 TRX/USDT | 18% | After 40 days |
| Plan 2 | 251 - 450 TRX/USDT | 20% | After 30 days |
| Plan 3 | 451 - 650 TRX/USDT | 22% | After 13 days |

## Referral Commissions (on profit, not deposit)

| Level | Commission |
|-------|-----------|
| Level 1 | 3% |
| Level 2 | 1% |
| Level 3 | 1% |
| Level 4 | 1% |
| Level 5 | 1% |

## Rules

- 1 active plan per tier per user
- Max 3 active plans at a time (one per tier)
- Cannot repeat a plan until its 60-day period ends
- Minimum withdrawal: 30 TRX
- Withdrawal fee: 5%
- Withdrawal schedule: Every Sunday
- No invite required to withdraw

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Copy `.env.example` to `.env` and fill in your bot token:
   ```bash
   cp .env.example .env
   ```
3. Run the bot:
   ```bash
   python bot.py
   ```

## Commands

### User Commands
- `/start` - Register
- `/plans` - View investment plans
- `/invest <plan> <amount> [TRX/USDT]` - Invest
- `/portfolio` - Check investments
- `/balance` - View balance
- `/withdraw <amount> [TRX/USDT]` - Withdraw (Sundays only)
- `/referral` - Referral link and stats
- `/howitworks` - How it works

### Admin Commands
- `/adminstats` - Dashboard
- `/dailyrun` - Trigger daily earnings
- `/pausepayouts` - Pause payouts (no trading profit)
- `/resumepayouts` - Resume payouts
- `/pending` - List pending withdrawals
- `/approve <id>` - Approve a withdrawal
