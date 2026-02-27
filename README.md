# Kimielbot

Telegram bot for an automated investment platform with tiered compensation plans, referral commissions, and daily profit distribution.

## Features

- **3 Tiered Investment Plans** with varying profit rates and lock periods
- **5-Level Referral System** with automatic commission distribution
- **Daily Profit Engine** for automated earnings crediting
- **TRX & USDT Support** as payment currencies
- **Admin Dashboard** for stats, withdrawal approval, and manual daily runs
- **"How It Works" Explainer** built into the bot (simple, Taglish)

## Investment Plans

| Plan | Amount Range | Profit (60 days) | Withdrawal Unlock |
|------|-------------|-------------------|-------------------|
| Plan 1 | 50 - 250 TRX/USDT | 18% | After 40 days |
| Plan 2 | 251 - 450 TRX/USDT | 20% | After 30 days |
| Plan 3 | 451 - 650 TRX/USDT | 22% | After 13 days |

## Referral Commissions

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

## Setup

1. Clone the repo
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and fill in:
   ```bash
   cp .env.example .env
   ```
4. Run the bot:
   ```bash
   python bot.py
   ```

## Commands

### User Commands
- `/start` - Register and see the main menu
- `/plans` - View investment plans
- `/invest <plan> <amount> [TRX/USDT]` - Make an investment
- `/portfolio` - Check investment status
- `/balance` - View your balance
- `/withdraw <amount> [TRX/USDT]` - Request a withdrawal
- `/referral` - Get your referral link and stats
- `/howitworks` - How the platform works
- `/help` - List all commands

### Admin Commands
- `/adminstats` - Platform statistics
- `/dailyrun` - Manually trigger daily earnings
- `/pending` - List pending withdrawals
- `/approve <id>` - Approve a withdrawal
- `/shutdown` - Stop the bot

## Project Structure

```
kimielbot/
├── bot.py              # Main entry point
├── config.py           # Plans, referral levels, settings
├── database.py         # SQLite setup and connection
├── complan.py          # Compensation plan engine
├── handlers/
│   ├── __init__.py     # Handler registration
│   ├── start.py        # /start, /help
│   ├── invest.py       # /plans, /invest
│   ├── withdraw.py     # /balance, /withdraw
│   ├── referral.py     # /referral
│   ├── info.py         # /howitworks, /portfolio
│   └── admin.py        # Admin commands
├── requirements.txt
├── .env.example
└── tests/
    └── test_complan.py
```
