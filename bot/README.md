# Polymarket Trading Bot

A Python bot that connects to the Polymarket CLOB API and trades automatically.

> **Default mode is paper trading (`DRY_RUN=true`).** Watch the logs first, then
> flip the flag once you're comfortable with what it would have traded.

## Strategy

**Cheap-YES scanner.** Each cycle the bot:

1. Pulls the most-active markets from the public Polymarket Gamma API.
2. Filters for binary markets where the YES token is priced between
   `MIN_YES_PRICE` and `MAX_YES_PRICE` (default 3¢ – 15¢) and 24h volume is
   above `MIN_MARKET_VOLUME`.
3. Looks up the live best ask on the CLOB and confirms it's still inside the
   threshold.
4. Places GTC limit buys at the best ask, sized to `ORDER_SIZE_USDC` per order.

**Take-profit / stop-loss auto-sell.** At the start of every cycle (live mode
only), the bot checks each open position against the live best bid:

- If `best_bid >= TAKE_PROFIT_PRICE` (default 30¢) → sell at the bid (profit)
- If `best_bid <= STOP_LOSS_PRICE` (default 1¢) → sell at the bid (cut losses)

Either way the position is removed from state, the daily spend budget is freed
up, and the realized PnL is logged.

It's a simple "asymmetric upside" play — small bets on long-tail outcomes the
market is pricing very low, exited when they re-rate. Easy to swap out: see
`bot/strategy.py`.

## Live dashboard

The bot also serves a real-time web dashboard on port `5000` (override with
`DASHBOARD_PORT`). It shows trades opened, win rate, realized PnL, unrealized
PnL, and the current open positions, refreshed every 5 seconds. In dry-run
mode it tracks paper trades; in live mode it tracks real trades. State is
read from `.bot_state.json`, which the strategy updates each cycle.

## Risk controls

All enforced in `bot/strategy.py`:

| Setting                  | Default | Meaning                                     |
| ------------------------ | ------- | ------------------------------------------- |
| `DRY_RUN`                | `true`  | If true, logs trades but never sends orders |
| `MAX_OPEN_POSITIONS`     | 10      | Cap on concurrent positions                 |
| `MAX_DAILY_SPEND_USDC`   | 50      | Hard daily USDC cap (resets at UTC midnight)|
| `MAX_ORDERS_PER_CYCLE`   | 3       | Cap on orders per loop iteration            |
| `ORDER_SIZE_USDC`        | 5       | Notional per order                          |

State is persisted to `.bot_state.json` so the daily cap survives restarts.

## Setup

1. Copy `.env.example` → `.env` and fill in `POLYMARKET_PRIVATE_KEY`
   (or set it as a Replit secret — the bot reads both).
2. Make sure your wallet on Polygon has USDC (and a tiny bit of MATIC for any
   Safe-relayed approvals if you're using a proxy wallet).
3. Start the workflow **`Polymarket Bot`** — it runs `python main.py`.

### Wallet types

- **Plain EOA wallet** (MetaMask, exported key): set
  `POLYMARKET_PRIVATE_KEY` only. Leave `POLYMARKET_FUNDER_ADDRESS` blank.
- **Polymarket email/browser-login account**: your funds live in a Magic-issued
  proxy wallet. Set `POLYMARKET_PRIVATE_KEY` to your signer key **and**
  `POLYMARKET_FUNDER_ADDRESS` to your proxy wallet address (visible in your
  Polymarket account → Wallet).

## Going live

1. Watch the dry-run logs for at least a few cycles.
2. Set `DRY_RUN=false`.
3. Restart the **`Polymarket Bot`** workflow.

## Files

```
main.py                       # entrypoint + main loop
bot/config.py                 # env-driven settings
bot/logger.py                 # log formatting
bot/polymarket_client.py      # CLOB + Gamma API wrapper
bot/strategy.py               # cheap-YES scanner + risk gates
.env.example                  # config template
```
