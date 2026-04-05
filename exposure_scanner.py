"""Exposure scanner — calculates LINK delta across arb wallet + LP position.

Delta = total LINK value (arb + LP) minus total USDC value (arb + LP).
Positive delta = long LINK exposure → need to short on HL.
Negative delta = short LINK exposure → need to long on HL.

When |delta| > HEDGE_EXPOSURE_THRESHOLD_USD → trigger hedge.
"""

from balance_tracker import BalanceTracker
import config


class ExposureScanner:
    def __init__(self):
        self.tracker = BalanceTracker()

    def get_exposure(self, lp_wallet: str = None) -> dict:
        """Calculate LINK exposure across arb wallet and LP position.

        The "neutral" state is 50/50 USDC/LINK by value.
        Exposure = how far we are from 50/50 in USD terms.

        Returns:
            {
                "link_price": current LINK price,
                "arb_usdc": USDC in arb wallet,
                "arb_link": LINK in arb wallet,
                "arb_link_value": LINK value in USD,
                "lp_usdc": USDC in LP position(s),
                "lp_link": LINK in LP position(s),
                "lp_link_value": LINK value in USD,
                "total_usdc": total USDC value across arb + LP,
                "total_link_value": total LINK value across arb + LP,
                "total_value": total portfolio value (arb + LP, excluding HL),
                "delta_usd": LINK exposure in USD (positive = long, negative = short),
                "delta_link": LINK exposure in LINK units,
                "should_hedge": whether exposure exceeds threshold,
                "hedge_direction": "short" or "long" or "none",
                "hedge_size_link": how much LINK to hedge,
            }
        """
        link_price = self.tracker._get_current_price()

        # Arb wallet balances
        arb = self.tracker.get_arb_balances()
        arb_usdc = arb["usdc"]
        arb_link = arb["link"]
        arb_link_value = arb_link * link_price

        # LP position balances
        lp_positions = self.tracker.get_lp_positions(lp_wallet)
        lp_usdc = sum(p["usdc_amount"] + p["fees_usdc"] for p in lp_positions)
        lp_link = sum(p["link_amount"] + p["fees_link"] for p in lp_positions)
        lp_link_value = lp_link * link_price

        # Totals (arb + LP only, HL is separate — it's the hedge)
        total_usdc = arb_usdc + lp_usdc
        total_link_value = arb_link_value + lp_link_value
        total_value = total_usdc + total_link_value

        # Delta: how much more LINK value we have than USDC value
        # Neutral = 50/50, so delta = link_value - usdc_value
        # Positive delta = we're long LINK, need to short on HL
        delta_usd = total_link_value - total_usdc
        delta_link = delta_usd / link_price if link_price > 0 else 0

        # Should we hedge?
        threshold = config.HEDGE_EXPOSURE_THRESHOLD_USD
        should_hedge = abs(delta_usd) > threshold

        if delta_usd > threshold:
            hedge_direction = "short"  # We're long LINK, short to neutralize
            hedge_size_link = delta_usd / link_price
        elif delta_usd < -threshold:
            hedge_direction = "long"  # We're short LINK, long to neutralize
            hedge_size_link = abs(delta_usd) / link_price
        else:
            hedge_direction = "none"
            hedge_size_link = 0

        return {
            "link_price": link_price,
            "arb_usdc": arb_usdc,
            "arb_link": arb_link,
            "arb_link_value": arb_link_value,
            "lp_usdc": lp_usdc,
            "lp_link": lp_link,
            "lp_link_value": lp_link_value,
            "total_usdc": total_usdc,
            "total_link_value": total_link_value,
            "total_value": total_value,
            "delta_usd": delta_usd,
            "delta_link": delta_link,
            "should_hedge": should_hedge,
            "hedge_direction": hedge_direction,
            "hedge_size_link": hedge_size_link,
        }

    def get_hl_position(self) -> dict:
        """Get current HL LINK position (for comparing with target hedge)."""
        hl = self.tracker.get_hl_account()
        for pos in hl.get("positions", []):
            if pos["coin"] == "LINK":
                return {
                    "size": pos["size"],  # Positive = long, negative = short
                    "entry_price": pos["entry_price"],
                    "unrealized_pnl": pos["unrealized_pnl"],
                }
        return {"size": 0, "entry_price": 0, "unrealized_pnl": 0}

    def print_exposure(self, lp_wallet: str = None):
        """Pretty-print exposure state."""
        exp = self.get_exposure(lp_wallet)
        hl_pos = self.get_hl_position()

        print("\n" + "=" * 55)
        print("  EXPOSURE SCAN")
        print(f"  LINK price: ${exp['link_price']:.4f}")
        print("=" * 55)
        print(f"  Arb wallet:  ${exp['arb_usdc']:.2f} USDC + {exp['arb_link']:.4f} LINK (${exp['arb_link_value']:.2f})")
        print(f"  LP position: ${exp['lp_usdc']:.2f} USDC + {exp['lp_link']:.4f} LINK (${exp['lp_link_value']:.2f})")
        print("-" * 55)
        print(f"  Total USDC side:  ${exp['total_usdc']:.2f}")
        print(f"  Total LINK side:  ${exp['total_link_value']:.2f}")
        print(f"  Total value:      ${exp['total_value']:.2f}")
        print("-" * 55)
        print(f"  DELTA: ${exp['delta_usd']:+.2f} ({exp['delta_link']:+.4f} LINK)")
        print(f"  Threshold: ${config.HEDGE_EXPOSURE_THRESHOLD_USD}")
        print(f"  Should hedge: {exp['should_hedge']} ({exp['hedge_direction']})")
        if exp["should_hedge"]:
            print(f"  Hedge size: {exp['hedge_size_link']:.4f} LINK")
        print("-" * 55)
        print(f"  HL position: {hl_pos['size']:+.1f} LINK (PnL: ${hl_pos['unrealized_pnl']:.4f})")
        print("=" * 55 + "\n")


if __name__ == "__main__":
    import sys
    scanner = ExposureScanner()
    lp_wallet = sys.argv[1] if len(sys.argv) > 1 else None
    scanner.print_exposure(lp_wallet)
