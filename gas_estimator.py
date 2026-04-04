"""Optimism gas cost estimator using QuickNode RPC."""

from web3 import Web3
import config

# Typical gas units for a Uniswap V3 exactInputSingle swap
TYPICAL_SWAP_GAS = 150_000


class GasEstimator:
    def __init__(self):
        self.w3 = Web3(Web3.HTTPProvider(config.QUICKNODE_HTTP))
        if not self.w3.is_connected():
            raise ConnectionError(f"Cannot connect to QuickNode: {config.QUICKNODE_HTTP}")

    def get_gas_price_wei(self) -> int:
        return self.w3.eth.gas_price

    def get_eth_price_usd(self) -> float:
        """Get ETH price from WETH/USDC pool on Optimism via QuickNode."""
        weth_usdc_pool = "0x85149247691df622eaF1a8Bd0CaFd40BC45154a9"
        pool_abi = [
            {
                "inputs": [],
                "name": "slot0",
                "outputs": [
                    {"internalType": "uint160", "name": "sqrtPriceX96", "type": "uint160"},
                    {"internalType": "int24", "name": "tick", "type": "int24"},
                    {"internalType": "uint16", "name": "observationIndex", "type": "uint16"},
                    {"internalType": "uint16", "name": "observationCardinality", "type": "uint16"},
                    {"internalType": "uint16", "name": "observationCardinalityNext", "type": "uint16"},
                    {"internalType": "uint8", "name": "feeProtocol", "type": "uint8"},
                    {"internalType": "bool", "name": "unlocked", "type": "bool"},
                ],
                "stateMutability": "view",
                "type": "function",
            },
            {
                "inputs": [],
                "name": "token0",
                "outputs": [{"internalType": "address", "name": "", "type": "address"}],
                "stateMutability": "view",
                "type": "function",
            },
        ]
        try:
            pool = self.w3.eth.contract(
                address=Web3.to_checksum_address(weth_usdc_pool), abi=pool_abi
            )
            slot0 = pool.functions.slot0().call()
            sqrt_price_x96 = slot0[0]
            token0 = pool.functions.token0().call().lower()

            price_raw = (sqrt_price_x96 / (2**96)) ** 2
            weth_addr = "0x4200000000000000000000000000000000000006"

            if token0 == weth_addr.lower():
                eth_price = price_raw * (10**12)
            else:
                eth_price = (1 / price_raw) / (10**12)

            return eth_price
        except Exception as e:
            print(f"[Gas] Failed to get on-chain ETH price: {e}, using fallback")
            return 2000.0

    def estimate_swap_cost_usd(self, gas_units: int = None) -> dict:
        """Estimate USD cost of a Uniswap V3 swap on Optimism.

        Args:
            gas_units: Override gas units. Defaults to typical 150k.

        Returns:
            {
                "gas_units": gas units,
                "gas_price_gwei": L2 gas price,
                "eth_price_usd": current ETH price,
                "eth_cost": cost in ETH,
                "usd_cost": L2 execution cost in USD,
                "usd_cost_with_l1": total including L1 data fee estimate,
            }
        """
        if gas_units is None:
            gas_units = TYPICAL_SWAP_GAS

        gas_price_wei = self.get_gas_price_wei()
        eth_price = self.get_eth_price_usd()

        eth_cost = (gas_units * gas_price_wei) / 1e18
        usd_cost = eth_cost * eth_price
        # L1 data fee is small post-EIP4844 (~$0.005)
        usd_cost_total = usd_cost + 0.005

        return {
            "gas_units": gas_units,
            "gas_price_gwei": gas_price_wei / 1e9,
            "eth_price_usd": eth_price,
            "eth_cost": eth_cost,
            "usd_cost": usd_cost,
            "usd_cost_with_l1": usd_cost_total,
        }
