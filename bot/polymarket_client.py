"""Thin wrapper around py-clob-client for Polymarket trading.

Handles client initialization (with or without browser-wallet funder),
API credential bootstrapping, market discovery, and order placement.
"""

from __future__ import annotations

import logging
from typing import Any, Iterator, Optional

import requests
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY, SELL


GAMMA_HOST = "https://gamma-api.polymarket.com"


class PolymarketClient:
    """Wraps the CLOB client with the things the bot actually needs."""

    def __init__(
        self,
        host: str,
        chain_id: int,
        private_key: Optional[str],
        funder_address: Optional[str],
        logger: logging.Logger,
    ) -> None:
        self.host = host
        self.chain_id = chain_id
        self.logger = logger
        self._client: Optional[ClobClient] = None

        if private_key:
            # signature_type=2 (POLY_GNOSIS_SAFE) is used when trading via a
            # browser/email login proxy wallet, in which case funder_address
            # is the proxy wallet that holds USDC. Otherwise we use EOA mode.
            if funder_address:
                self._client = ClobClient(
                    host=host,
                    key=private_key,
                    chain_id=chain_id,
                    signature_type=2,
                    funder=funder_address,
                )
            else:
                self._client = ClobClient(
                    host=host,
                    key=private_key,
                    chain_id=chain_id,
                )

            try:
                creds: ApiCreds = self._client.create_or_derive_api_creds()
                self._client.set_api_creds(creds)
                self.logger.info("Polymarket API credentials ready")
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(
                    "Could not derive API creds (read-only mode): %s", exc
                )

    # ------------------------------------------------------------------ #
    # Market data (Gamma API — public, no auth needed)
    # ------------------------------------------------------------------ #

    def iter_active_markets(self, limit_per_page: int = 100) -> Iterator[dict[str, Any]]:
        """Yield active, tradable, non-closed markets from the Gamma API."""
        offset = 0
        session = requests.Session()
        while True:
            resp = session.get(
                f"{GAMMA_HOST}/markets",
                params={
                    "active": "true",
                    "closed": "false",
                    "limit": limit_per_page,
                    "offset": offset,
                    "order": "volume24hr",
                    "ascending": "false",
                },
                timeout=20,
            )
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                return
            for market in batch:
                yield market
            if len(batch) < limit_per_page:
                return
            offset += limit_per_page

    # ------------------------------------------------------------------ #
    # Order book
    # ------------------------------------------------------------------ #

    def get_best_ask(self, token_id: str) -> Optional[float]:
        """Return the lowest ask price for a token, or None if no asks."""
        book = self._fetch_book(token_id)
        if book is None:
            return None
        asks = getattr(book, "asks", None) or []
        if not asks:
            return None
        try:
            return min(float(a.price) for a in asks)
        except (AttributeError, ValueError):
            return None

    def get_best_bid(self, token_id: str) -> Optional[float]:
        """Return the highest bid price for a token, or None if no bids."""
        book = self._fetch_book(token_id)
        if book is None:
            return None
        bids = getattr(book, "bids", None) or []
        if not bids:
            return None
        try:
            return max(float(b.price) for b in bids)
        except (AttributeError, ValueError):
            return None

    def _fetch_book(self, token_id: str):
        if self._client is None:
            return None
        try:
            return self._client.get_order_book(token_id)
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("get_order_book failed for %s: %s", token_id, exc)
            return None

    # ------------------------------------------------------------------ #
    # Trading
    # ------------------------------------------------------------------ #

    def place_buy_order(
        self,
        token_id: str,
        price: float,
        size_shares: float,
    ) -> dict[str, Any]:
        """Place a GTC limit buy order. Caller must have ensured DRY_RUN is off."""
        if self._client is None:
            raise RuntimeError("Trading client not initialized (missing private key)")

        args = OrderArgs(
            token_id=token_id,
            price=round(price, 4),
            size=round(size_shares, 2),
            side=BUY,
        )
        signed = self._client.create_order(args)
        return self._client.post_order(signed, OrderType.GTC)

    def place_sell_order(
        self,
        token_id: str,
        price: float,
        size_shares: float,
    ) -> dict[str, Any]:
        if self._client is None:
            raise RuntimeError("Trading client not initialized (missing private key)")

        args = OrderArgs(
            token_id=token_id,
            price=round(price, 4),
            size=round(size_shares, 2),
            side=SELL,
        )
        signed = self._client.create_order(args)
        return self._client.post_order(signed, OrderType.GTC)
