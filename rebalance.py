"""Rebalance arb wallet to 50/50 USDC/LINK via Uniswap Trading API.

Usage:
    python rebalance.py          # Dry run — shows what it would do
    python rebalance.py --execute  # Actually execute the swap
"""

import sys
from web3 import Web3
from eth_account import Account
from executor import Executor
import config

LINK_DECIMALS = 18
USDC_DECIMALS = 6

ERC20_ABI = [
    {"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf",
     "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
]


def get_balances(w3, wallet):
    usdc = w3.eth.contract(address=Web3.to_checksum_address(config.USDC_ADDRESS), abi=ERC20_ABI)
    link = w3.eth.contract(address=Web3.to_checksum_address(config.LINK_ADDRESS), abi=ERC20_ABI)

    usdc_bal = usdc.functions.balanceOf(wallet).call() / 10**USDC_DECIMALS
    link_bal = link.functions.balanceOf(wallet).call() / 10**LINK_DECIMALS
    return usdc_bal, link_bal


def get_link_price(w3):
    pool_abi = [{"inputs": [], "name": "slot0", "outputs": [
        {"name": "sqrtPriceX96", "type": "uint160"}, {"name": "tick", "type": "int24"},
        {"name": "", "type": "uint16"}, {"name": "", "type": "uint16"},
        {"name": "", "type": "uint16"}, {"name": "", "type": "uint8"},
        {"name": "", "type": "bool"}],
        "stateMutability": "view", "type": "function"}]
    pool = w3.eth.contract(address=Web3.to_checksum_address(config.POOL_ADDRESS), abi=pool_abi)
    slot0 = pool.functions.slot0().call()
    price_raw = (slot0[0] / (2**96)) ** 2
    return (1 / price_raw) * (10 ** (LINK_DECIMALS - USDC_DECIMALS))


def main():
    execute = "--execute" in sys.argv

    w3 = Web3(Web3.HTTPProvider(config.QUICKNODE_HTTP))
    account = Account.from_key(config.PRIVATE_KEY)
    wallet = account.address

    usdc_bal, link_bal = get_balances(w3, wallet)
    link_price = get_link_price(w3)
    link_val = link_bal * link_price
    total = usdc_bal + link_val
    target = total / 2

    print("=" * 50)
    print("  REBALANCE ARB WALLET TO 50/50 (via our pool)")
    print("=" * 50)
    print(f"  LINK price: ${link_price:.4f}")
    print(f"  USDC:  ${usdc_bal:.4f}")
    print(f"  LINK:  {link_bal:.6f} (${link_val:.2f})")
    print(f"  Total: ${total:.2f}")
    print(f"  Target: ${target:.2f} each side")
    print("-" * 50)

    if link_val > target:
        # Too much LINK, sell some for USDC
        excess_usd = link_val - target
        sell_link = excess_usd / link_price
        buy_link = False
        amount_usd = sell_link  # pool_swap expects LINK amount when selling
        print(f"  Action: SELL {sell_link:.6f} LINK (~${excess_usd:.2f}) for USDC")
    elif usdc_bal > target:
        # Too much USDC, buy LINK
        excess_usd = usdc_bal - target
        buy_link = True
        amount_usd = excess_usd
        print(f"  Action: BUY ${excess_usd:.2f} worth of LINK")
    else:
        print("  Already balanced!")
        return

    if not execute:
        print("\n  DRY RUN — add --execute to actually swap")
        print("=" * 50)
        return

    print("\n  Executing swap via Uniswap Trading API...")
    executor = Executor()
    result = executor.uniswap_api_swap(buy_link=buy_link, amount_in_usd=amount_usd)

    if result.get("success"):
        print(f"  Tx: {result['tx_hash']}")
        usdc_after, link_after = get_balances(w3, wallet)
        link_val_after = link_after * link_price
        print("\n  AFTER:")
        print(f"  USDC: ${usdc_after:.4f}")
        print(f"  LINK: {link_after:.6f} (${link_val_after:.2f})")
        print(f"  Total: ${usdc_after + link_val_after:.2f}")
    else:
        print(f"\n  Swap failed: {result.get('error', '')}")

    print("=" * 50)


if __name__ == "__main__":
    main()
