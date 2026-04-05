"""Main loop — Arbitrageur + Exposure Scanner + Hedger.

Each cycle:
1. Check pool price vs HL — arb if spread > 5 bps
2. Check LINK exposure across arb wallet + LP
3. If exposure > $10 threshold — hedge on HL
"""

import time
import sys
import json
from datetime import datetime, timezone
from arbitrage_engine import Arbitrageur
from exposure_scanner import ExposureScanner
from hedger import Hedger
from executor import Executor
import config

TRADE_LOG_FILE = "trades.log"


def log_event(event_type, data):
    """Append event to trades.log."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": event_type,
        **data,
    }
    with open(TRADE_LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


def run():
    """Main loop."""
    start_time = time.time()
    lp_wallet = config.LP_WALLET_ADDRESS or None

    print("=" * 60)
    print("  LINK/USDC Delta-Neutral Market Making")
    print("  Uniswap V3 (Optimism) + HyperLiquid Hedge")
    print(f"  Arb threshold: {config.ARB_THRESHOLD_BPS} bps")
    print(f"  Hedge threshold: ${config.HEDGE_EXPOSURE_THRESHOLD_USD}")
    print(f"  Arb trade: ${config.MIN_ARB_TRADE_USD}-${config.MAX_ARB_TRADE_USD}")
    print(f"  Execute: {config.EXECUTE_TRADES}")
    print(f"  Started: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 60)

    arb = Arbitrageur()
    scanner = ExposureScanner()
    executor = Executor() if config.EXECUTE_TRADES else None
    hedger = Hedger(executor, scanner)

    # Startup checks
    print("\n[Startup] Checking connections...")
    try:
        uni_data = arb.uni.get_pool_price()
        print(f"  Pool: {config.POOL_ADDRESS}")
        print(f"  Uni LINK: ${uni_data['price']:.4f}")
    except Exception as e:
        print(f"  FATAL: Uniswap: {e}")
        sys.exit(1)

    try:
        hl_mid = arb.hl.get_mid_price()
        print(f"  HL LINK: ${hl_mid:.4f}")
    except Exception as e:
        print(f"  FATAL: HyperLiquid: {e}")
        sys.exit(1)

    try:
        exp = scanner.get_exposure(lp_wallet)
        hl_pos = scanner.get_hl_position()
        print(f"  Arb wallet:  ${exp['arb_usdc']:.2f} USDC + {exp['arb_link']:.4f} LINK (${exp['arb_link_value']:.2f})")
        print(f"  LP position: ${exp['lp_usdc']:.2f} USDC + {exp['lp_link']:.4f} LINK (${exp['lp_link_value']:.2f})")
        print(f"  HL position: {hl_pos['size']:+.1f} LINK")
        print(f"  Delta: ${exp['delta_usd']:+.2f} ({exp['delta_link']:+.4f} LINK)")

        if abs(exp['delta_usd']) > config.HEDGE_EXPOSURE_THRESHOLD_USD:
            print(f"  WARNING: Exposure ${exp['delta_usd']:+.2f} exceeds threshold — hedger will correct on first cycle")
    except Exception as e:
        print(f"  FATAL: Exposure scan failed: {e}")
        sys.exit(1)

    print("\n[Running] Ctrl+C to stop\n")

    scan_count = 0
    arb_trades = 0
    hedge_trades = 0
    uni_api_calls = 0
    uni_api_errors = 0

    while True:
        try:
            scan_count += 1
            uptime = time.time() - start_time
            uptime_str = f"{int(uptime//3600)}h{int((uptime%3600)//60)}m{int(uptime%60)}s"

            # --- Step 1: Arb scan ---
            signal = arb.scan()
            uni_api_calls = arb.uni.api_calls
            uni_api_errors = arb.uni.api_errors

            if signal.should_trade:
                print(
                    f"[{scan_count}|{uptime_str}] ARB | "
                    f"spread={signal.spread_bps:+.1f}bps | "
                    f"{signal.direction} ${signal.trade_size_usd} | "
                    f"Uni=${signal.uni_price:.4f} HL=${signal.hl_price:.4f}"
                )

                if config.EXECUTE_TRADES:
                    result = arb.execute(signal)
                    log_event("arb", {
                        "direction": signal.direction,
                        "spread_bps": signal.spread_bps,
                        "uni_price": signal.uni_price,
                        "hl_price": signal.hl_price,
                        "trade_size_usd": signal.trade_size_usd,
                        "success": result.get("success", False),
                        "tx_hash": result.get("tx_hash", ""),
                    })
                    if result.get("success"):
                        arb_trades += 1
                        print(f"[Arb] Executed: {result.get('tx_hash', '')[:16]}...")
                    else:
                        print(f"[Arb] Failed: {result.get('error', '')}")
            else:
                # Compact no-trade line
                print(
                    f"[{scan_count}|{uptime_str}] "
                    f"spread={signal.spread_bps:+.1f}bps | "
                    f"Uni=${signal.uni_price:.4f} HL=${signal.hl_price:.4f} | "
                    f"{signal.reason}"
                )

            # --- Step 2: Exposure check + hedge ---
            try:
                hedge_result = hedger.check_and_hedge(lp_wallet)
                if hedge_result["hedged"]:
                    hedge_trades += 1
                    print(f"[Hedge] {hedge_result['action']}")
                    log_event("hedge", {
                        "delta_usd": hedge_result["delta_usd"],
                        "action": hedge_result["action"],
                        "success": True,
                        "hl_result": str(hedge_result.get("hl_result", "")),
                    })
                elif hedge_result["delta_usd"] and abs(hedge_result["delta_usd"]) > 1:
                    # Only print if delta is meaningful
                    pass  # Silent when within threshold
            except Exception as e:
                print(f"[Hedge] Error: {e}")

            # --- Stats every 50 scans ---
            if scan_count % 50 == 0:
                print(
                    f"  [Stats] scans={scan_count} arbs={arb_trades} hedges={hedge_trades} "
                    f"api_calls={uni_api_calls} api_err={uni_api_errors} "
                    f"uptime={uptime_str}"
                )

            time.sleep(config.POLL_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            uptime = time.time() - start_time
            print(f"\n{'=' * 60}")
            print(f"  Stopped after {int(uptime//60)}m{int(uptime%60)}s")
            print(f"  Scans: {scan_count}")
            print(f"  Arb trades: {arb_trades}")
            print(f"  Hedge trades: {hedge_trades}")
            print(f"  Uniswap API calls: {uni_api_calls}")
            print(f"  Uniswap API errors: {uni_api_errors}")
            print(f"{'=' * 60}")
            break
        except Exception as e:
            print(f"[Error] {e}")
            time.sleep(config.POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    if "--exposure" in sys.argv:
        lp = config.LP_WALLET_ADDRESS or None
        ExposureScanner().print_exposure(lp)
    else:
        run()
