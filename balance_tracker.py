"""Balance tracker — monitors all three parts of the system:
1. Arb wallet (USDC, LINK, ETH on Optimism)
2. LP position on Uniswap V3 (token amounts, fees earned, value)
3. HyperLiquid account (margin, positions, unrealized PnL)
"""

import requests
from web3 import Web3
from eth_account import Account
import config

LINK_DECIMALS = 18
USDC_DECIMALS = 6

ERC20_ABI = [
    {
        "inputs": [{"name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]

POSITION_MANAGER_ABI = [
    {
        "inputs": [{"name": "tokenId", "type": "uint256"}],
        "name": "positions",
        "outputs": [
            {"name": "nonce", "type": "uint96"},
            {"name": "operator", "type": "address"},
            {"name": "token0", "type": "address"},
            {"name": "token1", "type": "address"},
            {"name": "fee", "type": "uint24"},
            {"name": "tickLower", "type": "int24"},
            {"name": "tickUpper", "type": "int24"},
            {"name": "liquidity", "type": "uint128"},
            {"name": "feeGrowthInside0LastX128", "type": "uint256"},
            {"name": "feeGrowthInside1LastX128", "type": "uint256"},
            {"name": "tokensOwed0", "type": "uint128"},
            {"name": "tokensOwed1", "type": "uint128"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "owner", "type": "address"},
            {"name": "index", "type": "uint256"},
        ],
        "name": "tokenOfOwnerByIndex",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]

POOL_ABI = [
    {
        "inputs": [],
        "name": "slot0",
        "outputs": [
            {"name": "sqrtPriceX96", "type": "uint160"},
            {"name": "tick", "type": "int24"},
            {"name": "observationIndex", "type": "uint16"},
            {"name": "observationCardinality", "type": "uint16"},
            {"name": "observationCardinalityNext", "type": "uint16"},
            {"name": "feeProtocol", "type": "uint8"},
            {"name": "unlocked", "type": "bool"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
]


class BalanceTracker:
    def __init__(self):
        self.w3 = Web3(Web3.HTTPProvider(config.QUICKNODE_HTTP))
        self.arb_wallet = Account.from_key(config.PRIVATE_KEY).address

        self.link_token = self.w3.eth.contract(
            address=Web3.to_checksum_address(config.LINK_ADDRESS), abi=ERC20_ABI
        )
        self.usdc_token = self.w3.eth.contract(
            address=Web3.to_checksum_address(config.USDC_ADDRESS), abi=ERC20_ABI
        )
        self.position_manager = self.w3.eth.contract(
            address=Web3.to_checksum_address(config.POSITION_MANAGER),
            abi=POSITION_MANAGER_ABI,
        )
        self.pool_contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(config.POOL_ADDRESS), abi=POOL_ABI
        )

        self.hl_info_url = f"{config.HL_API_URL}/info"

    # -----------------------------------------------------------------
    # 1. ARB WALLET (Optimism)
    # -----------------------------------------------------------------
    def get_arb_balances(self) -> dict:
        """Get arb wallet token balances on Optimism."""
        eth_wei = self.w3.eth.get_balance(self.arb_wallet)
        usdc_raw = self.usdc_token.functions.balanceOf(self.arb_wallet).call()
        link_raw = self.link_token.functions.balanceOf(self.arb_wallet).call()

        return {
            "wallet": self.arb_wallet,
            "eth": eth_wei / 1e18,
            "usdc": usdc_raw / 10**USDC_DECIMALS,
            "link": link_raw / 10**LINK_DECIMALS,
        }

    # -----------------------------------------------------------------
    # 2. UNISWAP LP POSITION
    # -----------------------------------------------------------------
    def _get_current_tick(self) -> int:
        slot0 = self.pool_contract.functions.slot0().call()
        return slot0[1]

    def _get_current_price(self) -> float:
        """Get USDC per LINK from pool."""
        slot0 = self.pool_contract.functions.slot0().call()
        sqrt_price_x96 = slot0[0]
        price_raw = (sqrt_price_x96 / (2**96)) ** 2
        # token0=USDC, token1=LINK in our pool
        return (1 / price_raw) * (10 ** (LINK_DECIMALS - USDC_DECIMALS))

    def _calc_position_amounts(self, liquidity, tick_lower, tick_upper, current_tick, sqrt_price_x96):
        """Calculate token amounts for a concentrated liquidity position."""
        import math

        sqrt_p = sqrt_price_x96 / (2**96)
        sqrt_a = math.sqrt(1.0001**tick_lower)
        sqrt_b = math.sqrt(1.0001**tick_upper)

        if current_tick < tick_lower:
            # All in token0 (USDC)
            amount0 = liquidity * (1 / sqrt_a - 1 / sqrt_b)
            amount1 = 0
        elif current_tick >= tick_upper:
            # All in token1 (LINK)
            amount0 = 0
            amount1 = liquidity * (sqrt_b - sqrt_a)
        else:
            # In range
            amount0 = liquidity * (1 / sqrt_p - 1 / sqrt_b)
            amount1 = liquidity * (sqrt_p - sqrt_a)

        return amount0 / 10**USDC_DECIMALS, amount1 / 10**LINK_DECIMALS

    def get_lp_positions(self, lp_wallet: str = None) -> list:
        """Get all LINK/USDC LP positions for a wallet.

        Args:
            lp_wallet: Wallet address that owns the LP. Defaults to arb wallet.

        Returns list of position dicts.
        """
        wallet = Web3.to_checksum_address(lp_wallet or self.arb_wallet)

        num_positions = self.position_manager.functions.balanceOf(wallet).call()
        if num_positions == 0:
            return []

        slot0 = self.pool_contract.functions.slot0().call()
        sqrt_price_x96 = slot0[0]
        current_tick = slot0[1]
        link_price = self._get_current_price()

        positions = []
        for i in range(num_positions):
            token_id = self.position_manager.functions.tokenOfOwnerByIndex(wallet, i).call()
            pos = self.position_manager.functions.positions(token_id).call()

            token0 = pos[2].lower()
            token1 = pos[3].lower()
            fee = pos[4]
            tick_lower = pos[5]
            tick_upper = pos[6]
            liquidity = pos[7]
            tokens_owed0 = pos[10]
            tokens_owed1 = pos[11]

            # Only include LINK/USDC positions
            is_link_usdc = (
                (token0 == config.USDC_ADDRESS.lower() and token1 == config.LINK_ADDRESS.lower())
                or (token0 == config.LINK_ADDRESS.lower() and token1 == config.USDC_ADDRESS.lower())
            )
            if not is_link_usdc:
                continue

            # Calculate current token amounts
            usdc_amount, link_amount = self._calc_position_amounts(
                liquidity, tick_lower, tick_upper, current_tick, sqrt_price_x96
            )

            # Unclaimed fees
            fees_usdc = tokens_owed0 / 10**USDC_DECIMALS
            fees_link = tokens_owed1 / 10**LINK_DECIMALS

            in_range = tick_lower <= current_tick < tick_upper
            total_value = usdc_amount + (link_amount * link_price) + fees_usdc + (fees_link * link_price)

            positions.append({
                "token_id": token_id,
                "fee_tier": fee,
                "tick_lower": tick_lower,
                "tick_upper": tick_upper,
                "liquidity": liquidity,
                "in_range": in_range,
                "usdc_amount": usdc_amount,
                "link_amount": link_amount,
                "fees_usdc": fees_usdc,
                "fees_link": fees_link,
                "total_value_usd": total_value,
            })

        return positions

    # -----------------------------------------------------------------
    # 3. HYPERLIQUID ACCOUNT
    # -----------------------------------------------------------------
    def _hl_post(self, payload: dict) -> dict:
        resp = requests.post(self.hl_info_url, json=payload, timeout=5)
        resp.raise_for_status()
        return resp.json()

    def get_hl_account(self) -> dict:
        """Get HyperLiquid account state: margin, positions, PnL."""
        if not config.HL_WALLET_ADDRESS:
            return {"error": "HL_WALLET_ADDRESS not set"}

        # Get user state (positions + margin)
        state = self._hl_post({
            "type": "clearinghouseState",
            "user": config.HL_WALLET_ADDRESS,
        })

        margin_summary = state.get("marginSummary", {})
        account_value = float(margin_summary.get("accountValue", 0))
        total_margin_used = float(margin_summary.get("totalMarginUsed", 0))
        withdrawable = float(margin_summary.get("withdrawable", 0))

        # Parse positions
        positions = []
        for pos in state.get("assetPositions", []):
            p = pos.get("position", {})
            coin = p.get("coin", "")
            if coin != "LINK":
                continue

            size = float(p.get("szi", 0))
            entry_price = float(p.get("entryPx", 0))
            unrealized_pnl = float(p.get("unrealizedPnl", 0))
            margin_used = float(p.get("marginUsed", 0))
            leverage = p.get("leverage", {})
            lev_value = float(leverage.get("value", 0)) if isinstance(leverage, dict) else float(leverage)

            positions.append({
                "coin": coin,
                "size": size,
                "side": "LONG" if size > 0 else "SHORT" if size < 0 else "FLAT",
                "entry_price": entry_price,
                "unrealized_pnl": unrealized_pnl,
                "margin_used": margin_used,
                "leverage": lev_value,
            })

        return {
            "wallet": config.HL_WALLET_ADDRESS,
            "account_value": account_value,
            "total_margin_used": total_margin_used,
            "withdrawable": withdrawable,
            "positions": positions,
        }

    # -----------------------------------------------------------------
    # FULL SNAPSHOT
    # -----------------------------------------------------------------
    def snapshot(self, lp_wallet: str = None) -> dict:
        """Get a full balance snapshot across all three parts."""
        link_price = self._get_current_price()

        arb = self.get_arb_balances()
        arb["link_value_usd"] = arb["link"] * link_price
        arb["total_usd"] = arb["usdc"] + arb["link_value_usd"]

        lp = self.get_lp_positions(lp_wallet)
        lp_total = sum(p["total_value_usd"] for p in lp)

        hl = self.get_hl_account()

        total_value = arb["total_usd"] + lp_total + hl.get("account_value", 0)

        return {
            "link_price": link_price,
            "arb_wallet": arb,
            "lp_positions": lp,
            "lp_total_usd": lp_total,
            "hyperliquid": hl,
            "total_value_usd": total_value,
        }

    def print_snapshot(self, lp_wallet: str = None):
        """Pretty-print a full balance snapshot."""
        snap = self.snapshot(lp_wallet)

        print("\n" + "=" * 60)
        print("  BALANCE SNAPSHOT")
        print(f"  LINK price: ${snap['link_price']:.4f}")
        print("=" * 60)

        # Arb wallet
        arb = snap["arb_wallet"]
        print(f"\n  [1] ARB WALLET ({arb['wallet'][:10]}...)")
        print(f"      ETH:   {arb['eth']:.6f}")
        print(f"      USDC:  {arb['usdc']:.4f}")
        print(f"      LINK:  {arb['link']:.6f} (${arb['link_value_usd']:.2f})")
        print(f"      Total: ${arb['total_usd']:.2f}")

        # LP positions
        print(f"\n  [2] UNISWAP LP (total: ${snap['lp_total_usd']:.2f})")
        for p in snap["lp_positions"]:
            status = "IN RANGE" if p["in_range"] else "OUT OF RANGE"
            print(f"      Position #{p['token_id']} ({p['fee_tier']/10000:.2f}%) [{status}]")
            print(f"        USDC: {p['usdc_amount']:.4f}  LINK: {p['link_amount']:.6f}")
            print(f"        Fees: {p['fees_usdc']:.4f} USDC + {p['fees_link']:.6f} LINK")
            print(f"        Value: ${p['total_value_usd']:.2f}")

        if not snap["lp_positions"]:
            print("      No LINK/USDC positions found for this wallet")

        # HyperLiquid
        hl = snap["hyperliquid"]
        print(f"\n  [3] HYPERLIQUID ({hl.get('wallet', 'N/A')[:10]}...)")
        if "error" in hl:
            print(f"      {hl['error']}")
        else:
            print(f"      Account value: ${hl['account_value']:.2f}")
            print(f"      Margin used:   ${hl['total_margin_used']:.2f}")
            print(f"      Withdrawable:  ${hl['withdrawable']:.2f}")
            for pos in hl.get("positions", []):
                print(f"      LINK {pos['side']}: {abs(pos['size']):.1f} @ ${pos['entry_price']:.4f}")
                print(f"        Unrealized PnL: ${pos['unrealized_pnl']:.4f}")
                print(f"        Leverage: {pos['leverage']:.1f}x")
            if not hl.get("positions"):
                print("      No LINK positions")

        # Total
        print(f"\n  {'-' * 40}")
        print(f"  TOTAL VALUE: ${snap['total_value_usd']:.2f}")
        print("=" * 60 + "\n")


if __name__ == "__main__":
    import sys
    tracker = BalanceTracker()
    lp_wallet = sys.argv[1] if len(sys.argv) > 1 else None
    tracker.print_snapshot(lp_wallet)
