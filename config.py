import os
from dotenv import load_dotenv

load_dotenv()

# --- QuickNode RPC (for gas estimation only) ---
QUICKNODE_HTTP = os.getenv(
    "QUICKNODE_HTTP",
    "https://summer-rough-pool.optimism.quiknode.pro/966251bfc8c4d50007a3dc6f47455ad48ccb9762/",
)
QUICKNODE_WSS = os.getenv(
    "QUICKNODE_WSS",
    "wss://summer-rough-pool.optimism.quiknode.pro/966251bfc8c4d50007a3dc6f47455ad48ccb9762/",
)

# --- Wallet ---
PRIVATE_KEY = os.getenv("PRIVATE_KEY", "")  # For signing Uniswap swaps
HL_PRIVATE_KEY = os.getenv("HL_PRIVATE_KEY", "")  # HyperLiquid API wallet key
HL_WALLET_ADDRESS = os.getenv("HL_WALLET_ADDRESS", "")

# --- Tokens on Optimism ---
LINK_ADDRESS = "0x350a791Bfc2C21F9Ed5d10980Dad2e2638FFa7f6"
USDC_ADDRESS = "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85"

# --- Uniswap V3 on Optimism ---
POOL_ADDRESS = "0x2eD85aD8093FdefF2f5B0b1CfcA560dDc03c48Ed"  # LINK/USDC 0.05%
POOL_FEE = 500  # 0.05% = 500

# Uniswap Trading API
UNISWAP_API_URL = "https://trade-api.gateway.uniswap.org/v1"
UNISWAP_API_KEY = os.getenv("UNISWAP_API_KEY", "")

# --- HyperLiquid ---
HL_API_URL = "https://api.hyperliquid.xyz"

# --- Arbitrage Parameters ---
MIN_PROFIT_USD = 0.0  # Allow breakeven/slight loss trades
MAX_TRADE_SIZE_USD = 10.0  # Trade size in USD (HL minimum is $10)
SLIPPAGE_TOLERANCE = 0.50  # 50% — loose for testing
POLL_INTERVAL_SECONDS = 2  # How often to check for opportunities
EXECUTE_TRADES = False  # Scan only until wallet is funded

