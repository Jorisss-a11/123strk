"""HyperLiquid API client for reading LINK perp price and placing trades."""

import requests
import config


class HyperLiquidClient:
    def __init__(self):
        self.info_url = f"{config.HL_API_URL}/info"
        self.coin = "LINK"
        self._meta = None

    def _post_info(self, payload: dict) -> dict:
        resp = requests.post(self.info_url, json=payload, timeout=5)
        resp.raise_for_status()
        return resp.json()

    def get_meta(self) -> dict:
        """Fetch exchange metadata (asset list, size decimals, etc.)."""
        if self._meta:
            return self._meta
        self._meta = self._post_info({"type": "meta"})
        return self._meta

    def get_asset_index(self) -> int:
        """Get LINK's asset index in the HL universe."""
        meta = self.get_meta()
        for i, asset in enumerate(meta["universe"]):
            if asset["name"] == self.coin:
                return i
        raise ValueError(f"{self.coin} not found in HyperLiquid universe")

    def get_size_decimals(self) -> int:
        """Get the size precision for LINK (e.g. 0 = whole numbers, 1 = 0.1 increments)."""
        meta = self.get_meta()
        for asset in meta["universe"]:
            if asset["name"] == self.coin:
                return asset["szDecimals"]
        return 0

    def get_mid_price(self) -> float:
        """Get LINK mid price from allMids endpoint."""
        data = self._post_info({"type": "allMids"})
        if self.coin in data:
            return float(data[self.coin])
        raise ValueError(f"No mid price found for {self.coin}")

    def get_best_bid_ask(self) -> dict:
        """Get best bid/ask from L2 book (top of book only).

        Returns:
            {
                "best_bid": float,
                "best_ask": float,
                "mid": float,
                "spread": float,
                "spread_pct": float,
            }
        """
        data = self._post_info({"type": "l2Book", "coin": self.coin})
        levels = data["levels"]

        best_bid = float(levels[0][0]["px"]) if levels[0] else 0
        best_ask = float(levels[1][0]["px"]) if levels[1] else 0
        mid = (best_bid + best_ask) / 2 if best_bid and best_ask else 0
        spread = best_ask - best_bid
        spread_pct = (spread / mid * 100) if mid else 0

        return {
            "best_bid": best_bid,
            "best_ask": best_ask,
            "mid": mid,
            "spread": spread,
            "spread_pct": spread_pct,
        }

    def get_fees(self) -> dict:
        """Get trading fees for the configured wallet, or return defaults."""
        if config.HL_WALLET_ADDRESS:
            try:
                data = self._post_info({
                    "type": "userFees",
                    "user": config.HL_WALLET_ADDRESS,
                })
                return {
                    "taker": float(data.get("takerRate", "0.00045")),
                    "maker": float(data.get("makerRate", "0.00015")),
                }
            except Exception:
                pass

        # Default tier 0 fees
        return {"taker": 0.00045, "maker": 0.00015}

    def get_fill_price(self, size_usd: float, is_buy: bool) -> dict:
        """Get the price you'd fill at for a given trade size.

        For small sizes ($50-1000), best bid/ask is the fill price.
        LINK is very liquid on HL so top-of-book is sufficient.

        Returns:
            {
                "fill_price": best bid (sell) or best ask (buy),
                "size_link": LINK amount (rounded to size decimals),
                "feasible": True if size >= $10 min,
            }
        """
        bba = self.get_best_bid_ask()
        fill_price = bba["best_ask"] if is_buy else bba["best_bid"]

        sz_decimals = self.get_size_decimals()
        size_link = round(size_usd / fill_price, sz_decimals) if fill_price > 0 else 0

        feasible = size_usd >= 10 and size_link > 0

        return {
            "fill_price": fill_price,
            "size_link": size_link,
            "feasible": feasible,
        }
