"""HL Hedger — adjusts HyperLiquid position to neutralize LINK delta.

When exposure scanner says "short 2 LINK", and we already have -1 LINK on HL,
we only need to short 1 more LINK to reach target.
"""

import math
from executor import Executor
from exposure_scanner import ExposureScanner
import config


class Hedger:
    def __init__(self, executor: Executor, scanner: ExposureScanner):
        self.executor = executor
        self.scanner = scanner

    def check_and_hedge(self, lp_wallet: str = None) -> dict:
        """Check exposure and hedge if needed.

        Returns:
            {
                "hedged": bool,
                "delta_usd": current delta before hedge,
                "action": description of what was done,
                "hl_result": HL order result or None,
            }
        """
        exposure = self.scanner.get_exposure(lp_wallet)
        hl_pos = self.scanner.get_hl_position()

        # Net exposure = on-chain delta + HL position
        # If we're long 12 LINK on-chain (delta_link=+12) and short 11 on HL (size=-11),
        # net exposure = 12 + (-11) = 1 LINK long — only need to short 1 more
        onchain_delta_link = exposure["delta_link"]
        current_hl_size = hl_pos["size"]  # Positive = long, negative = short
        link_price = exposure["link_price"]

        net_exposure_link = onchain_delta_link + current_hl_size
        net_exposure_usd = net_exposure_link * link_price

        if abs(net_exposure_usd) <= config.HEDGE_EXPOSURE_THRESHOLD_USD:
            return {
                "hedged": False,
                "delta_usd": net_exposure_usd,
                "action": f"Net exposure ${net_exposure_usd:+.2f} within threshold ${config.HEDGE_EXPOSURE_THRESHOLD_USD}",
                "hl_result": None,
            }

        # We need to hedge the net exposure, not the full on-chain delta
        # Positive net = still long LINK → short more on HL
        # Negative net = over-hedged → buy back on HL
        size_change = -net_exposure_link  # How much to add to HL position

        if abs(size_change) < 0.1:
            return {
                "hedged": False,
                "delta_usd": net_exposure_usd,
                "action": f"Hedge change too small ({size_change:+.1f} LINK)",
                "hl_result": None,
            }

        # Check if the hedge order meets HL $10 minimum
        hedge_value = abs(size_change) * link_price
        if hedge_value < 10:
            # Round up to meet minimum
            min_size = math.ceil(10 / link_price * 10) / 10  # Round to 0.1
            if size_change < 0:
                size_change = -min_size
            else:
                size_change = min_size

        if size_change < 0:
            # Need to short more (or reduce long)
            is_buy = False
            size_link = abs(size_change)
            action_desc = f"SHORT {size_link:.1f} LINK on HL (net ${net_exposure_usd:+.2f})"
        else:
            # Need to long more (or reduce short)
            is_buy = True
            size_link = abs(size_change)
            action_desc = f"LONG {size_link:.1f} LINK on HL (net ${net_exposure_usd:+.2f})"

        target_hl = current_hl_size + size_change
        print(f"[Hedger] {action_desc}")
        print(f"[Hedger] HL: {current_hl_size:+.1f} -> {target_hl:+.1f} LINK | on-chain delta: {onchain_delta_link:+.1f}")

        if not self.executor:
            return {
                "hedged": False,
                "delta_usd": net_exposure_usd,
                "action": f"DRY RUN: would {action_desc}",
                "hl_result": None,
            }

        result = self.executor.hl_market_order(
            is_buy=is_buy,
            size_usd=size_link * link_price,
            current_price=link_price,
        )

        return {
            "hedged": result.get("success", False),
            "delta_usd": net_exposure_usd,
            "action": action_desc,
            "hl_result": result,
        }
