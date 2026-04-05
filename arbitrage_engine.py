"""Arbitrageur — corrects our Uniswap pool price to match HyperLiquid.

Only trades when spread exceeds ARB_THRESHOLD_BPS.
Direction: always corrects OUR pool toward HL price.
"""

from dataclasses import dataclass
from web3 import Web3
from eth_account import Account
from uniswap_client import UniswapV3Client
from hyperliquid_client import HyperLiquidClient
from gas_estimator import GasEstimator
from executor import Executor
import config


@dataclass
class ArbSignal:
    spread_bps: float  # Spread in basis points (positive = uni cheaper)
    uni_price: float
    hl_price: float
    direction: str  # "buy_uni" or "sell_uni"
    trade_size_usd: float
    should_trade: bool
    reason: str


class Arbitrageur:
    def __init__(self):
        self.uni = UniswapV3Client()
        self.hl = HyperLiquidClient()
        self.gas = GasEstimator()
        self.executor = Executor() if config.EXECUTE_TRADES else None

        # Balance check setup
        self.w3 = self.uni.w3
        erc20_abi = [{"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf",
                      "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"}]
        self.usdc_contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(config.USDC_ADDRESS), abi=erc20_abi)
        self.link_contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(config.LINK_ADDRESS), abi=erc20_abi)
        self.wallet = Account.from_key(config.PRIVATE_KEY).address if config.PRIVATE_KEY else None

    def get_wallet_balances(self) -> dict:
        """Get arb wallet USDC and LINK balances."""
        usdc = self.usdc_contract.functions.balanceOf(self.wallet).call() / 10**6
        link = self.link_contract.functions.balanceOf(self.wallet).call() / 10**18
        return {"usdc": usdc, "link": link}

    def scan(self) -> ArbSignal:
        """Check if pool price deviates from HL by more than threshold.

        Uses Uniswap Trading API quote to get a realistic effective price
        (accounts for routing, slippage, fees) rather than raw pool mid.
        """
        # Get HL reference price
        hl_bba = self.hl.get_best_bid_ask()
        hl_price = hl_bba["mid"]

        # Get Uniswap effective price via Trading API quote
        # Quote a small buy to see what price we'd actually get
        quote = self.uni.quote_swap(amount_in_usd=2.0, buy_link=True)
        if quote:
            uni_price = quote["effective_price"]
        else:
            # Fallback to pool mid if API fails
            uni_data = self.uni.get_pool_price()
            uni_price = uni_data["price"]

        # Spread in bps: positive means uni is cheaper than HL
        spread_bps = ((hl_price - uni_price) / hl_price) * 10000

        if spread_bps > 0:
            # Uni cheaper → buy LINK on Uni (pushes uni price up toward HL)
            direction = "buy_uni"
        else:
            # Uni more expensive → sell LINK on Uni (pushes uni price down toward HL)
            direction = "sell_uni"

        should_trade = abs(spread_bps) >= config.ARB_THRESHOLD_BPS

        # Determine trade size from available balance, capped by MAX_ARB_TRADE_USD
        trade_size = 0
        reason = "Spread below threshold"
        if should_trade:
            balances = self.get_wallet_balances()
            if direction == "buy_uni":
                available = balances["usdc"]
            else:
                available = balances["link"] * uni_price

            trade_size = min(available, config.MAX_ARB_TRADE_USD)

            if trade_size < config.MIN_ARB_TRADE_USD:
                should_trade = False
                reason = f"Available ${available:.2f} < min ${config.MIN_ARB_TRADE_USD}"
            else:
                reason = f"Spread {abs(spread_bps):.1f} bps > {config.ARB_THRESHOLD_BPS} bps"

        return ArbSignal(
            spread_bps=spread_bps,
            uni_price=uni_price,
            hl_price=hl_price,
            direction=direction,
            trade_size_usd=trade_size,
            should_trade=should_trade,
            reason=reason,
        )

    def execute(self, signal: ArbSignal) -> dict:
        """Execute the arb trade via Uniswap Trading API."""
        if not self.executor:
            return {"success": False, "error": "Execution disabled"}

        if signal.direction == "buy_uni":
            print(f"[Arb] Buying LINK via Uniswap API (${signal.trade_size_usd:.2f})")
            result = self.executor.uniswap_api_swap(
                buy_link=True,
                amount_in_usd=signal.trade_size_usd,
            )
        else:
            link_amount = signal.trade_size_usd / signal.uni_price
            print(f"[Arb] Selling {link_amount:.4f} LINK via Uniswap API")
            result = self.executor.uniswap_api_swap(
                buy_link=False,
                amount_in_usd=link_amount,
            )

        return result
