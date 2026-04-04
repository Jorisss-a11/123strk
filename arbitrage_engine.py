"""Core arbitrage logic: detect mispricing, check feasibility, execute."""

from dataclasses import dataclass
from uniswap_client import UniswapV3Client
from hyperliquid_client import HyperLiquidClient
from gas_estimator import GasEstimator
from executor import Executor
import config


@dataclass
class ArbitrageOpportunity:
    direction: str  # "buy_uni_sell_hl" or "buy_hl_sell_uni"
    uni_price: float  # Uniswap mid price (USDC/LINK)
    hl_price: float  # HyperLiquid mid price (USDC/LINK)
    spread_pct: float  # Raw spread percentage
    trade_size_usd: float  # Trade size in USD
    uni_effective_price: float  # Price after slippage on Uniswap
    hl_fill_price: float  # Expected fill price on HL
    uni_fee_usd: float  # Uniswap pool fee cost
    hl_fee_usd: float  # HyperLiquid taker fee cost
    gas_cost_usd: float  # Optimism gas cost
    total_cost_usd: float  # Sum of all costs
    gross_profit_usd: float  # Profit before costs
    net_profit_usd: float  # Profit after costs
    feasible: bool  # Whether the trade can be executed
    reason: str  # Why it's feasible or not


class ArbitrageEngine:
    def __init__(self):
        self.uni = UniswapV3Client()
        self.hl = HyperLiquidClient()
        self.gas = GasEstimator()
        self.executor = Executor() if config.EXECUTE_TRADES else None

    def scan(self, trade_size_usd: float = None) -> ArbitrageOpportunity:
        """Scan for arbitrage opportunity between Uniswap and HyperLiquid.

        Args:
            trade_size_usd: Size to trade in USD. Defaults to config.MAX_TRADE_SIZE_USD.

        Returns:
            ArbitrageOpportunity with full breakdown.
        """
        if trade_size_usd is None:
            trade_size_usd = config.MAX_TRADE_SIZE_USD

        # --- 1. Get prices from both venues ---
        uni_data = self.uni.get_pool_price()
        uni_price = uni_data["price"]

        hl_bba = self.hl.get_best_bid_ask()
        hl_price = hl_bba["mid"]

        # --- 2. Determine direction ---
        # If Uniswap is cheaper -> buy on Uniswap, sell on HL
        # If HL is cheaper -> buy on HL, sell on Uniswap
        spread_pct = (hl_price - uni_price) / uni_price * 100

        if uni_price < hl_price:
            direction = "buy_uni_sell_hl"
            buy_link_on_uni = True
            is_buy_hl = False  # selling on HL
        else:
            direction = "buy_hl_sell_uni"
            buy_link_on_uni = False
            is_buy_hl = True  # buying on HL

        # --- 3. Simulate both legs ---
        # Uniswap side
        uni_quote = self.uni.quote_swap(trade_size_usd, buy_link=buy_link_on_uni)
        if uni_quote is None:
            return ArbitrageOpportunity(
                direction=direction, uni_price=uni_price, hl_price=hl_price,
                spread_pct=spread_pct, trade_size_usd=trade_size_usd,
                uni_effective_price=0, hl_fill_price=0,
                uni_fee_usd=0, hl_fee_usd=0, gas_cost_usd=0,
                total_cost_usd=0, gross_profit_usd=0, net_profit_usd=0,
                feasible=False, reason="Uniswap quote failed",
            )

        # HL side — use best bid/ask (sufficient for our trade sizes)
        hl_fill = self.hl.get_fill_price(trade_size_usd, is_buy=is_buy_hl)

        # --- 4. Check feasibility ---
        reasons = []

        if not hl_fill["feasible"]:
            reasons.append("HL trade not feasible (size rounds to 0 or below $10 min)")

        # HL minimum order value is $10
        if trade_size_usd < 10:
            reasons.append(f"Trade size ${trade_size_usd} below HL minimum $10")

        if uni_data["liquidity"] == 0:
            reasons.append("No liquidity in Uniswap pool")

        # --- 5. Calculate costs ---
        # Uniswap fee is already embedded in the quote (pool takes 0.05%),
        # but let's track it explicitly for the breakdown
        uni_fee_usd = trade_size_usd * (config.POOL_FEE / 1_000_000)  # 0.05%

        hl_fees = self.hl.get_fees()
        hl_fee_usd = trade_size_usd * hl_fees["taker"]

        # Use gas estimate from Uniswap API if available, fallback to our estimator
        api_gas_wei = uni_quote.get("gas_fee_wei", 0)
        if api_gas_wei > 0:
            eth_price = self.gas.get_eth_price_usd()
            gas_cost_usd = (api_gas_wei / 1e18) * eth_price
        else:
            gas_data = self.gas.estimate_swap_cost_usd()
            gas_cost_usd = gas_data["usd_cost_with_l1"]

        total_cost_usd = uni_fee_usd + hl_fee_usd + gas_cost_usd

        # --- 6. Calculate profit ---
        uni_eff = uni_quote["effective_price"]
        hl_eff = hl_fill["fill_price"]

        if direction == "buy_uni_sell_hl":
            # Buy LINK on Uniswap at uni_eff, sell on HL at hl_eff
            link_amount = uni_quote["amount_out"]
            gross_profit_usd = (hl_eff - uni_eff) * link_amount
        else:
            # Buy LINK on HL at hl_eff, sell on Uniswap at uni_eff
            link_amount = hl_fill["size_link"]
            gross_profit_usd = (uni_eff - hl_eff) * link_amount

        # Note: uni_fee is already reflected in the effective price from the quoter,
        # so we only subtract HL fee and gas from gross profit
        net_profit_usd = gross_profit_usd - hl_fee_usd - gas_cost_usd

        feasible = len(reasons) == 0 and net_profit_usd > config.MIN_PROFIT_USD
        if not reasons and net_profit_usd <= config.MIN_PROFIT_USD:
            reasons.append(
                f"Net profit ${net_profit_usd:.4f} below min ${config.MIN_PROFIT_USD}"
            )

        return ArbitrageOpportunity(
            direction=direction,
            uni_price=uni_price,
            hl_price=hl_price,
            spread_pct=spread_pct,
            trade_size_usd=trade_size_usd,
            uni_effective_price=uni_eff,
            hl_fill_price=hl_eff,
            uni_fee_usd=uni_fee_usd,
            hl_fee_usd=hl_fee_usd,
            gas_cost_usd=gas_cost_usd,
            total_cost_usd=total_cost_usd,
            gross_profit_usd=gross_profit_usd,
            net_profit_usd=net_profit_usd,
            feasible=feasible,
            reason="; ".join(reasons) if reasons else "Profitable",
        )

    def execute(self, opp: ArbitrageOpportunity) -> dict:
        """Execute both legs of the arbitrage trade.

        Returns:
            {"success": bool, "uni_result": dict, "hl_result": dict}
        """
        if not self.executor:
            return {"success": False, "error": "Execution disabled"}

        print("\n>>> EXECUTING ARBITRAGE <<<")

        if opp.direction == "buy_uni_sell_hl":
            # Leg 1: Buy LINK on Uniswap (USDC -> LINK)
            print(f"[Leg 1] Buy LINK on Uniswap: ${opp.trade_size_usd} USDC -> LINK")
            uni_result = self.executor.uniswap_swap(
                buy_link=True,
                amount_in_usd=opp.trade_size_usd,
                min_amount_out=0,  # No slippage protection for testing
            )
            if not uni_result["success"]:
                print(f"[Leg 1] FAILED: {uni_result.get('error', 'unknown')}")
                return {"success": False, "uni_result": uni_result, "hl_result": None}

            # Leg 2: Sell LINK on HL (short LINK perp)
            print(f"[Leg 2] Sell LINK on HyperLiquid")
            hl_result = self.executor.hl_market_order(
                is_buy=False,
                size_usd=opp.trade_size_usd,
                current_price=opp.hl_price,
            )
        else:
            # Leg 1: Buy LINK on HL (long LINK perp)
            print(f"[Leg 1] Buy LINK on HyperLiquid")
            hl_result = self.executor.hl_market_order(
                is_buy=True,
                size_usd=opp.trade_size_usd,
                current_price=opp.hl_price,
            )
            if not hl_result["success"]:
                print(f"[Leg 1] FAILED: {hl_result.get('error', 'unknown')}")
                return {"success": False, "uni_result": None, "hl_result": hl_result}

            # Leg 2: Sell LINK on Uniswap (LINK -> USDC)
            link_amount = hl_result.get("size_link", opp.trade_size_usd / opp.hl_price)
            print(f"[Leg 2] Sell {link_amount} LINK on Uniswap")
            uni_result = self.executor.uniswap_swap(
                buy_link=False,
                amount_in_usd=link_amount,  # This is LINK amount, not USD
                min_amount_out=0,
            )

        success = uni_result.get("success", False) and hl_result.get("success", False)
        print(f"\n>>> EXECUTION {'COMPLETE' if success else 'FAILED'} <<<\n")

        return {"success": success, "uni_result": uni_result, "hl_result": hl_result}

    def print_opportunity(self, opp: ArbitrageOpportunity):
        """Pretty-print an arbitrage opportunity."""
        print("\n" + "=" * 60)
        print("  ARBITRAGE SCAN RESULT")
        print("=" * 60)
        print(f"  Direction:      {opp.direction}")
        print(f"  Uniswap price:  ${opp.uni_price:.4f}")
        print(f"  HL price:       ${opp.hl_price:.4f}")
        print(f"  Spread:         {opp.spread_pct:+.4f}%")
        print(f"  Trade size:     ${opp.trade_size_usd:.2f}")
        print("-" * 60)
        print(f"  Uni eff. price: ${opp.uni_effective_price:.4f} (routed)")
        print(f"  HL fill price:  ${opp.hl_fill_price:.4f}")
        print("-" * 60)
        print(f"  Uni fee (0.05%):  ${opp.uni_fee_usd:.4f}")
        print(f"  HL taker fee:     ${opp.hl_fee_usd:.4f}")
        print(f"  Gas cost (OP):    ${opp.gas_cost_usd:.4f}")
        print(f"  Total costs:      ${opp.total_cost_usd:.4f}")
        print("-" * 60)
        print(f"  Gross profit:   ${opp.gross_profit_usd:.4f}")
        print(f"  NET PROFIT:     ${opp.net_profit_usd:.4f}")
        print(f"  Feasible:       {opp.feasible}")
        print(f"  Reason:         {opp.reason}")
        print("=" * 60 + "\n")
