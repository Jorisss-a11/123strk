"""Main entry point — polls for arbitrage opportunities between Uniswap V3 and HyperLiquid."""

import time
import sys
import json
from datetime import datetime, timezone
from arbitrage_engine import ArbitrageEngine
import config

TRADE_LOG_FILE = "trades.log"


def log_trade(opp, result):
    """Append trade details to trades.log."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "direction": opp.direction,
        "trade_size_usd": opp.trade_size_usd,
        "uni_price": opp.uni_price,
        "hl_price": opp.hl_price,
        "spread_pct": opp.spread_pct,
        "uni_effective_price": opp.uni_effective_price,
        "hl_fill_price": opp.hl_fill_price,
        "net_profit_usd": opp.net_profit_usd,
        "success": result.get("success", False),
        "uni_tx_hash": result.get("uni_result", {}).get("tx_hash", ""),
        "hl_response": result.get("hl_result", {}),
    }
    with open(TRADE_LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")
    print(f"[Log] Trade logged to {TRADE_LOG_FILE}")


def run_scanner():
    """Run the arbitrage scanner in a loop."""
    start_time = time.time()

    print("=" * 60)
    print("  LINK/USDC Arbitrage Scanner")
    print("  Uniswap V3 (Optimism) <-> HyperLiquid Perp")
    print(f"  Trade size: ${config.MAX_TRADE_SIZE_USD}")
    print(f"  Min profit: ${config.MIN_PROFIT_USD}")
    print(f"  Poll interval: {config.POLL_INTERVAL_SECONDS}s")
    print(f"  Started at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 60)

    engine = ArbitrageEngine()

    # Verify connections on startup
    print("\n[Startup] Checking connections...")
    try:
        uni_data = engine.uni.get_pool_price()
        print(f"  Uniswap pool: {config.POOL_ADDRESS}")
        print(f"  Uniswap LINK price: ${uni_data['price']:.4f}")
    except Exception as e:
        print(f"  FATAL: Cannot connect to Uniswap: {e}")
        sys.exit(1)

    try:
        hl_mid = engine.hl.get_mid_price()
        print(f"  HyperLiquid LINK mid: ${hl_mid:.4f}")
    except Exception as e:
        print(f"  FATAL: Cannot connect to HyperLiquid: {e}")
        sys.exit(1)

    try:
        gas = engine.gas.estimate_swap_cost_usd()
        print(f"  Optimism gas estimate: ${gas['usd_cost_with_l1']:.4f}")
    except Exception as e:
        print(f"  WARNING: Gas estimation failed: {e}")

    print("\n[Scanner] Running... (Ctrl+C to stop)\n")

    scan_count = 0
    opportunities_found = 0
    trades_executed = 0
    trades_failed = 0
    uni_api_errors = 0
    hl_api_errors = 0

    while True:
        try:
            scan_count += 1
            uptime = time.time() - start_time
            uptime_str = f"{int(uptime//3600)}h{int((uptime%3600)//60)}m{int(uptime%60)}s"

            opp = engine.scan()

            # Track API errors
            if opp.reason == "Uniswap quote failed":
                uni_api_errors += 1

            # Compact status line with uptime
            status = "OPPORTUNITY" if opp.feasible else "no-arb"
            print(
                f"[{scan_count}|{uptime_str}] {status} | "
                f"Uni=${opp.uni_price:.4f} HL=${opp.hl_price:.4f} | "
                f"spread={opp.spread_pct:+.3f}% | "
                f"net=${opp.net_profit_usd:+.4f} | "
                f"{opp.reason}"
            )

            # Print stats every 50 scans
            if scan_count % 50 == 0:
                print(
                    f"  [Stats] scans={scan_count} opps={opportunities_found} "
                    f"trades={trades_executed} failed={trades_failed} "
                    f"uni_api_calls={engine.uni.api_calls} uni_api_err={engine.uni.api_errors} "
                    f"uptime={uptime_str}"
                )

            if opp.feasible:
                opportunities_found += 1
                engine.print_opportunity(opp)
                if config.EXECUTE_TRADES:
                    result = engine.execute(opp)
                    log_trade(opp, result)
                    if result["success"]:
                        trades_executed += 1
                        print("[Scanner] Trade executed successfully!")
                    else:
                        trades_failed += 1
                        print(f"[Scanner] Trade failed: {result}")

            time.sleep(config.POLL_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            uptime = time.time() - start_time
            print(f"\n{'=' * 60}")
            print(f"  Scanner stopped after {int(uptime//60)}m{int(uptime%60)}s")
            print(f"  Scans: {scan_count}")
            print(f"  Opportunities: {opportunities_found}")
            print(f"  Trades executed: {trades_executed}")
            print(f"  Trades failed: {trades_failed}")
            print(f"  Uniswap API calls: {engine.uni.api_calls}")
            print(f"  Uniswap API errors: {engine.uni.api_errors}")
            print(f"{'=' * 60}")
            break
        except Exception as e:
            print(f"[Scanner] Error: {e}")
            time.sleep(config.POLL_INTERVAL_SECONDS)


def run_once():
    """Run a single scan and print results — useful for testing."""
    engine = ArbitrageEngine()
    opp = engine.scan()
    engine.print_opportunity(opp)
    return opp


if __name__ == "__main__":
    if "--once" in sys.argv:
        run_once()
    else:
        run_scanner()
