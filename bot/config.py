"""Configuration for the Polymarket trading bot.

All values can be overridden via environment variables.
"""

import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


def _get_float(key: str, default: float) -> float:
    raw = os.getenv(key)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _get_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _get_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Config:
    # --- Wallet / API ---
    private_key: Optional[str]
    funder_address: Optional[str]  # Optional: proxy/funder address (for browser/email login wallets)
    chain_id: int                  # Polygon = 137
    host: str                      # CLOB API host

    # --- Trading mode ---
    dry_run: bool                  # True = paper trading, no real orders
    poll_interval_seconds: int     # How often the strategy loop runs

    # --- Strategy: cheap-yes scanner ---
    # Scans active markets and buys YES when price <= max_yes_price.
    max_yes_price: float           # e.g. 0.15 = only buy when YES <= 15c
    min_yes_price: float           # e.g. 0.03 = avoid sub-penny noise
    order_size_usdc: float         # USDC notional per order
    min_market_volume: float       # Skip thinly traded markets (24h volume floor)

    # --- Exit rules ---
    take_profit_price: float       # Sell an open YES position when its price >= this
    stop_loss_price: float         # Sell an open YES position when its price <= this

    # --- Risk limits ---
    max_open_positions: int        # Cap concurrent positions
    max_daily_spend_usdc: float    # Stop trading after this much USDC spent today
    max_orders_per_cycle: int      # Cap orders placed per loop iteration

    # --- Logging ---
    log_level: str


def load_config() -> Config:
    return Config(
        private_key=os.getenv("POLYMARKET_PRIVATE_KEY"),
        funder_address=os.getenv("POLYMARKET_FUNDER_ADDRESS"),
        chain_id=_get_int("POLYMARKET_CHAIN_ID", 137),
        host=os.getenv("POLYMARKET_HOST", "https://clob.polymarket.com"),

        dry_run=_get_bool("DRY_RUN", True),
        poll_interval_seconds=_get_int("POLL_INTERVAL_SECONDS", 60),

        max_yes_price=_get_float("MAX_YES_PRICE", 0.15),
        min_yes_price=_get_float("MIN_YES_PRICE", 0.03),
        order_size_usdc=_get_float("ORDER_SIZE_USDC", 5.0),
        min_market_volume=_get_float("MIN_MARKET_VOLUME", 10000.0),

        take_profit_price=_get_float("TAKE_PROFIT_PRICE", 0.30),
        stop_loss_price=_get_float("STOP_LOSS_PRICE", 0.01),

        max_open_positions=_get_int("MAX_OPEN_POSITIONS", 10),
        max_daily_spend_usdc=_get_float("MAX_DAILY_SPEND_USDC", 50.0),
        max_orders_per_cycle=_get_int("MAX_ORDERS_PER_CYCLE", 3),

        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )
