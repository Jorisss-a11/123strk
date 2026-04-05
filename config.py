import os
from dotenv import load_dotenv

load_dotenv()

# --- QuickNode RPC ---
QUICKNODE_HTTP = os.getenv(
    "QUICKNODE_HTTP",
    "https://summer-rough-pool.optimism.quiknode.pro/966251bfc8c4d50007a3dc6f47455ad48ccb9762/",
)
QUICKNODE_WSS = os.getenv(
    "QUICKNODE_WSS",
    "wss://summer-rough-pool.optimism.quiknode.pro/966251bfc8c4d50007a3dc6f47455ad48ccb9762/",
)

# --- Wallets ---
PRIVATE_KEY = os.getenv("PRIVATE_KEY", "")  # Arb wallet (also signs Uniswap swaps)
HL_PRIVATE_KEY = os.getenv("HL_PRIVATE_KEY", "")  # HyperLiquid API wallet key
HL_WALLET_ADDRESS = os.getenv("HL_WALLET_ADDRESS", "")
LP_WALLET_ADDRESS = os.getenv("LP_WALLET_ADDRESS", "")  # Wallet that owns LP position

# --- Tokens on Optimism ---
LINK_ADDRESS = "0x350a791Bfc2C21F9Ed5d10980Dad2e2638FFa7f6"
USDC_ADDRESS = "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85"

# --- Uniswap V3 on Optimism ---
POOL_ADDRESS = "0x2eD85aD8093FdefF2f5B0b1CfcA560dDc03c48Ed"  # LINK/USDC 0.05%
POOL_FEE = 500  # 0.05% = 500
POSITION_MANAGER = "0xC36442b4a4522E871399CD717aBDD847Ab11FE88"

# Uniswap Trading API
UNISWAP_API_URL = "https://trade-api.gateway.uniswap.org/v1"
UNISWAP_API_KEY = os.getenv("UNISWAP_API_KEY", "")

# --- HyperLiquid ---
HL_API_URL = "https://api.hyperliquid.xyz"

# --- Uniswap V3 Direct SwapRouter (for arb trades against our pool) ---
SWAP_ROUTER = "0xE592427A0AEce92De3Edee1F18E0157C05861564"

# --- Strategy Parameters ---
# Arbitrage: only arb when spread > this many bps
ARB_THRESHOLD_BPS = 5  # 5 bps = 0.05%

# Hedging: hedge when LINK exposure exceeds this USD value
HEDGE_EXPOSURE_THRESHOLD_USD = 10.0  # Constant $10 for now

# Trade sizes
MAX_ARB_TRADE_USD = 5.0  # Max single arb trade (no HL minimum constraint)
MIN_ARB_TRADE_USD = 1.0  # Min arb trade to bother with (gas must be worth it)
SLIPPAGE_TOLERANCE = 0.50  # 50% — loose for testing

# Execution
EXECUTE_TRADES = True
POLL_INTERVAL_SECONDS = 2
