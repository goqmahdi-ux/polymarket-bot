"""Trading strategy: cheap-YES scanner with take-profit / stop-loss exits.

Tracks both live and paper-trade positions in a single state file so the
dashboard can show real-time stats. Risk caps and exit rules apply in both
modes; state is cleanly separated by `mode` per position.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .config import Config
from .polymarket_client import PolymarketClient


STATE_FILE = Path(".bot_state.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class TradeIntent:
    market_question: str
    token_id: str
    outcome: str
    price: float
    size_shares: float
    notional_usdc: float


PNL_HISTORY_MAX = 500


def _empty_state() -> dict[str, Any]:
    return {
        "date": str(date.today()),
        "spent_usdc": {"live": 0.0, "paper": 0.0},
        "open_positions": [],
        "closed_positions": [],
        "pnl_history": {"live": [], "paper": []},
    }


class CheapYesStrategy:
    def __init__(
        self,
        config: Config,
        client: PolymarketClient,
        logger: logging.Logger,
    ) -> None:
        self.config = config
        self.client = client
        self.logger = logger
        self.state = self._load_state()

    # ----------------------- state persistence ----------------------- #

    def _load_state(self) -> dict[str, Any]:
        if STATE_FILE.exists():
            try:
                loaded = json.loads(STATE_FILE.read_text())
            except json.JSONDecodeError:
                loaded = {}
            base = _empty_state()
            base.update({k: v for k, v in loaded.items() if k in base})
            # Migrate older shapes (spent_usdc was a flat float).
            if not isinstance(base.get("spent_usdc"), dict):
                base["spent_usdc"] = {"live": 0.0, "paper": 0.0}
            base.setdefault("closed_positions", [])
            if not isinstance(base.get("pnl_history"), dict):
                base["pnl_history"] = {"live": [], "paper": []}
            base["pnl_history"].setdefault("live", [])
            base["pnl_history"].setdefault("paper", [])
            return base
        return _empty_state()

    def _save_state(self) -> None:
        STATE_FILE.write_text(json.dumps(self.state, indent=2))

    def _roll_day_if_needed(self) -> None:
        today = str(date.today())
        if self.state.get("date") != today:
            self.logger.info(
                "New trading day. Resetting daily spend (live $%.2f / paper $%.2f)",
                self.state["spent_usdc"].get("live", 0.0),
                self.state["spent_usdc"].get("paper", 0.0),
            )
            self.state["date"] = today
            self.state["spent_usdc"] = {"live": 0.0, "paper": 0.0}
            self._save_state()

    @property
    def _mode(self) -> str:
        return "paper" if self.config.dry_run else "live"

    # ------------------------- core loop ----------------------------- #

    def _record_pnl_snapshot(self) -> None:
        mode = self._mode
        open_pos = [p for p in self.state["open_positions"] if p.get("mode") == mode]
        closed_pos = [p for p in self.state["closed_positions"] if p.get("mode") == mode]
        realized = round(sum(float(p.get("realized_pnl_usdc", 0.0)) for p in closed_pos), 4)
        unrealized = round(
            sum(
                (float(p.get("latest_bid", p.get("price", 0.0))) - float(p.get("price", 0.0)))
                * float(p.get("size", 0.0))
                for p in open_pos
            ),
            4,
        )
        history = self.state["pnl_history"].setdefault(mode, [])
        history.append(
            {
                "t": _now_iso(),
                "realized": realized,
                "unrealized": unrealized,
                "total": round(realized + unrealized, 4),
            }
        )
        if len(history) > PNL_HISTORY_MAX:
            del history[: len(history) - PNL_HISTORY_MAX]

    def run_cycle(self) -> None:
        try:
            self._roll_day_if_needed()
            self._manage_open_positions()

            spent = self.state["spent_usdc"].get(self._mode, 0.0)
            if spent >= self.config.max_daily_spend_usdc:
                self.logger.info(
                    "Daily spend cap hit ($%.2f / $%.2f) for %s mode. Skipping new entries.",
                    spent,
                    self.config.max_daily_spend_usdc,
                    self._mode,
                )
                return

            open_in_mode = [
                p for p in self.state["open_positions"] if p.get("mode") == self._mode
            ]
            if len(open_in_mode) >= self.config.max_open_positions:
                self.logger.info(
                    "Max open positions reached (%d) for %s mode. Skipping new entries.",
                    len(open_in_mode),
                    self._mode,
                )
                return

            candidates = self._find_candidates()
            if not candidates:
                self.logger.info("No candidate markets matched the strategy this cycle.")
                return

            self.logger.info("Found %d candidate market(s).", len(candidates))

            placed = 0
            for intent in candidates:
                if placed >= self.config.max_orders_per_cycle:
                    break
                if (
                    self.state["spent_usdc"].get(self._mode, 0.0) + intent.notional_usdc
                    > self.config.max_daily_spend_usdc
                ):
                    continue
                if (
                    len([p for p in self.state["open_positions"] if p.get("mode") == self._mode])
                    >= self.config.max_open_positions
                ):
                    break

                self._execute(intent)
                placed += 1
        finally:
            self._record_pnl_snapshot()
            self._save_state()

    # ------------------------ exit rules ----------------------------- #

    def _manage_open_positions(self) -> None:
        """Mark positions to market and apply take-profit / stop-loss rules."""
        if not self.state["open_positions"]:
            return

        tp = self.config.take_profit_price
        sl = self.config.stop_loss_price
        remaining: list[dict[str, Any]] = []

        for pos in self.state["open_positions"]:
            token_id = pos["token_id"]
            best_bid = self.client.get_best_bid(token_id)

            if best_bid is None:
                # Keep last-known mark; just hold.
                remaining.append(pos)
                continue

            pos["latest_bid"] = best_bid
            pos["latest_bid_at"] = _now_iso()

            if best_bid >= tp:
                exit_reason = "TAKE-PROFIT"
            elif best_bid <= sl:
                exit_reason = "STOP-LOSS"
            else:
                remaining.append(pos)
                continue

            if not self._exit_position(pos, best_bid, exit_reason):
                remaining.append(pos)

        self.state["open_positions"] = remaining
        self._save_state()

    def _exit_position(
        self,
        pos: dict[str, Any],
        exit_price: float,
        reason: str,
    ) -> bool:
        token_id = pos["token_id"]
        entry_price = float(pos.get("price", 0.0))
        size = float(pos.get("size", 0.0))
        cost = float(pos.get("notional_usdc", 0.0))
        proceeds = round(exit_price * size, 4)
        pnl = round(proceeds - cost, 4)
        mode = pos.get("mode", self._mode)

        if mode == "live":
            try:
                self.client.place_sell_order(
                    token_id=token_id, price=exit_price, size_shares=size
                )
            except Exception as exc:  # noqa: BLE001
                self.logger.error(
                    "%s sell failed for %s: %s",
                    reason,
                    pos.get("question", token_id)[:60],
                    exc,
                )
                return False

        sign = "+" if pnl >= 0 else "-"
        tag = "[LIVE]" if mode == "live" else "[PAPER]"
        self.logger.info(
            "%s %s SELL %.2f @ %.3f (entry %.3f, PnL %s$%.2f) — %s",
            tag, reason, size, exit_price, entry_price, sign, abs(pnl),
            pos.get("question", "")[:80],
        )

        # Free up the daily spend budget.
        self.state["spent_usdc"][mode] = max(
            0.0, round(self.state["spent_usdc"].get(mode, 0.0) - cost, 4)
        )

        closed = dict(pos)
        closed.update(
            {
                "exit_price": exit_price,
                "exit_reason": reason,
                "realized_pnl_usdc": pnl,
                "win": pnl > 0,
                "closed_at": _now_iso(),
            }
        )
        self.state["closed_positions"].append(closed)
        return True

    # --------------------- candidate discovery ----------------------- #

    def _find_candidates(self) -> list[TradeIntent]:
        intents: list[TradeIntent] = []
        scanned = 0
        max_scan = 200

        held_token_ids = {
            p["token_id"]
            for p in self.state["open_positions"]
            if p.get("mode") == self._mode
        }

        for market in self.client.iter_active_markets(limit_per_page=100):
            scanned += 1
            if scanned > max_scan:
                break

            try:
                volume = float(market.get("volume24hr") or 0.0)
            except (TypeError, ValueError):
                volume = 0.0
            if volume < self.config.min_market_volume:
                continue

            outcomes = self._safe_json_list(market.get("outcomes"))
            prices = self._safe_json_list(market.get("outcomePrices"))
            token_ids = self._safe_json_list(market.get("clobTokenIds"))
            if not (outcomes and prices and token_ids):
                continue
            if len(outcomes) != len(prices) or len(outcomes) != len(token_ids):
                continue

            for outcome, price_str, token_id in zip(outcomes, prices, token_ids):
                if str(outcome).strip().lower() != "yes":
                    continue
                try:
                    price = float(price_str)
                except (TypeError, ValueError):
                    continue
                if not (self.config.min_yes_price <= price <= self.config.max_yes_price):
                    continue
                if not token_id or token_id in held_token_ids:
                    continue

                size = round(self.config.order_size_usdc / max(price, 0.01), 2)
                if size <= 0:
                    continue

                intents.append(
                    TradeIntent(
                        market_question=str(market.get("question") or "")[:120],
                        token_id=str(token_id),
                        outcome=str(outcome),
                        price=price,
                        size_shares=size,
                        notional_usdc=round(price * size, 4),
                    )
                )

        intents.sort(key=lambda i: i.price)
        return intents

    @staticmethod
    def _safe_json_list(value: Any) -> list[Any]:
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return []
            return parsed if isinstance(parsed, list) else []
        return []

    # ------------------------- execution ----------------------------- #

    def _execute(self, intent: TradeIntent) -> None:
        live_price: Optional[float] = self.client.get_best_ask(intent.token_id)
        if live_price is not None and live_price > self.config.max_yes_price:
            self.logger.info(
                "Skipping '%s' — best ask %.3f above threshold %.3f",
                intent.market_question[:60],
                live_price,
                self.config.max_yes_price,
            )
            return

        execution_price = live_price if live_price is not None else intent.price
        cost = round(execution_price * intent.size_shares, 4)
        tag = "[LIVE]" if self._mode == "live" else "[DRY-RUN]"

        if self._mode == "live":
            try:
                resp = self.client.place_buy_order(
                    token_id=intent.token_id,
                    price=execution_price,
                    size_shares=intent.size_shares,
                )
                self.logger.info(
                    "[LIVE] BUY %.2f @ %.3f — %s — response: %s",
                    intent.size_shares, execution_price, intent.market_question, resp,
                )
            except Exception as exc:  # noqa: BLE001
                self.logger.error(
                    "Order failed for %s: %s", intent.market_question, exc
                )
                return
        else:
            self.logger.info(
                "%s BUY %.2f shares of YES @ %.3f ($%.2f) — %s",
                tag, intent.size_shares, execution_price, cost, intent.market_question,
            )

        self.state["spent_usdc"][self._mode] = round(
            self.state["spent_usdc"].get(self._mode, 0.0) + cost, 4
        )
        self.state["open_positions"].append(
            {
                "token_id": intent.token_id,
                "question": intent.market_question,
                "price": execution_price,
                "size": intent.size_shares,
                "notional_usdc": cost,
                "latest_bid": execution_price,
                "latest_bid_at": _now_iso(),
                "opened_at": _now_iso(),
                "mode": self._mode,
            }
        )
