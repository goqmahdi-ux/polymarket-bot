"""Polymarket auto-trading bot — entrypoint.

Loads configuration, wires up the Polymarket client and strategy, then runs
the strategy loop forever (or once, if RUN_ONCE=true).
"""

import os
import time
import traceback

from bot.config import load_config
from bot.dashboard import start_dashboard_in_thread
from bot.logger import setup_logger
from bot.polymarket_client import PolymarketClient
from bot.strategy import CheapYesStrategy


def main() -> None:
    config = load_config()
    logger = setup_logger(config.log_level)

    logger.info("=" * 60)
    logger.info("Polymarket trading bot starting")
    logger.info("Mode: %s", "DRY-RUN (paper trading)" if config.dry_run else "LIVE TRADING")
    logger.info("Host: %s | Chain: %d", config.host, config.chain_id)
    logger.info(
        "Strategy: cheap-YES scanner | range [%.2f, %.2f] | size $%.2f",
        config.min_yes_price,
        config.max_yes_price,
        config.order_size_usdc,
    )
    logger.info(
        "Risk: max %d positions | $%.2f daily spend | %d orders/cycle",
        config.max_open_positions,
        config.max_daily_spend_usdc,
        config.max_orders_per_cycle,
    )
    logger.info("Poll interval: %ds", config.poll_interval_seconds)
    logger.info("=" * 60)

    if not config.private_key:
        if config.dry_run:
            logger.warning(
                "No POLYMARKET_PRIVATE_KEY set. Running in dry-run with public market "
                "data only — order book lookups will be skipped."
            )
        else:
            logger.error(
                "POLYMARKET_PRIVATE_KEY is required for live trading. Exiting."
            )
            return

    client = PolymarketClient(
        host=config.host,
        chain_id=config.chain_id,
        private_key=config.private_key,
        funder_address=config.funder_address,
        logger=logger,
    )
    strategy = CheapYesStrategy(config=config, client=client, logger=logger)

    dashboard_port = int(os.getenv("DASHBOARD_PORT", "5000"))
    start_dashboard_in_thread(config=config, port=dashboard_port, logger=logger)

    run_once = os.getenv("RUN_ONCE", "").strip().lower() in ("1", "true", "yes")

    while True:
        try:
            logger.info("--- Strategy cycle start ---")
            strategy.run_cycle()
            logger.info("--- Strategy cycle done ---")
        except Exception as exc:  # noqa: BLE001
            logger.error("Cycle failed: %s\n%s", exc, traceback.format_exc())

        if run_once:
            logger.info("RUN_ONCE set — exiting after one cycle.")
            return

        time.sleep(config.poll_interval_seconds)


if __name__ == "__main__":
    main()
