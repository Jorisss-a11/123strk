# Uniswap Trading API - Feedback from Live Arbitrage Bot

## Context
Built a LINK/USDC arbitrage bot on Optimism using the Uniswap Trading API for swap execution and quotes. The bot detects mispricing between a Uniswap V3 pool and HyperLiquid perps, then executes both legs.

**Test period:** April 4-5, 2026  
**Chain:** Optimism (chain ID 10)  
**Pair:** LINK/USDC  
**Trade size:** $10 per swap  
**API calls made:** 2000+ quote requests, many successful swap executions

---

## What Worked Well

### 1. Quote Reliability
- Over 1000+ `/quote` calls, **error rate was ~0.2%** (occasional 404 "No quotes available" — maybe 1 in 50 calls)
- Quotes returned consistently in <1 second
- CLASSIC routing on Optimism worked perfectly every time

### 2. Smart Routing Made a Huge Difference
- Our pool had only $100 of liquidity. Direct SwapRouter would give us $16.37 effective price for 1 LINK (857% slippage)
- The Trading API routed across larger pools and gave us **$8.63 effective price** — basically no slippage
- This turned an impossible -$4.73 trade into a profitable +$0.09 trade
- The API automatically found the optimal path without us needing to discover pools

### 3. Gas Estimation
- The `gasFee` field in the quote response was useful for pre-trade profit calculations
- Gas estimates were accurate

### 4. Simulation
- `simulateTransaction: true` in the `/swap` endpoint caught a `TRANSFER_FROM_FAILED` before we wasted gas — very valuable

---

## Issues Encountered

### 1. Permit2 Signature Handling is Confusing
**Problem:** When no `permitData` is returned (token already approved), sending `"signature": "0x"` causes a 400 error:
```
"signature" with value "0x" fails to match the required pattern: /^0x[a-fA-F0-9]+$/
```
**Workaround:** Don't include `signature` field at all when `permitData` is null.  
**Suggestion:** The API should accept `"0x"` or an empty signature gracefully when no permit is needed, or the docs should explicitly state to omit the field.

### 2. Quote Expiration is Undocumented
**Problem:** We got a quote, then spent ~10 seconds doing an approval tx, then called `/swap` — got a 400 error. The quote had expired.  
**Workaround:** Do approvals first, then get a fresh quote immediately before `/swap`.  
**Suggestion:** Document the quote TTL (seems to be ~30 seconds). Include an `expiresAt` field in the quote response.

### 3. 404 "No Quotes Available" is Intermittent
**Problem:** About 1 in 50 quote requests returns 404 with `"No quotes available"` for LINK/USDC on Optimism, even though the next request 2 seconds later succeeds.  
**Suggestion:** Return a more specific error — is it a temporary routing failure? Rate limiting? Helps with retry logic.

### 4. `/check_approval` Returns Approval for Already-Approved Tokens
**Problem:** After we approved USDC for Permit2 (max uint256), the `/check_approval` endpoint still sometimes returned an approval tx. Might be related to Permit2 sub-approvals vs ERC20 approvals.  
**Suggestion:** Clearer docs on the approval flow — when does Permit2 need a fresh signature vs when can you skip it?

### 5. `simulateTransaction` Failure Returns 404 (Not 400)
**Problem:** When simulation fails (e.g., `TRANSFER_FROM_FAILED`), the HTTP status is 404 with `errorCode: "NotFound"`. This is semantically wrong — the resource exists, the simulation just failed.  
**Suggestion:** Return 422 or 400 with a dedicated error code like `SIMULATION_FAILED`.

---

## API Call Volume for a Simple Arb Bot

Running a polling scanner at 2-second intervals:
- **Quote calls:** ~720/hour (~17,000/day)
- **Swap calls:** Only when executing (few per day)
- **Approval checks:** Only on execution attempts

For a production bot, we'd want WebSocket support or a lighter "price check" endpoint that doesn't do full routing — just to check if a quote is roughly viable before requesting the full route.

---

## Summary

The Uniswap Trading API is excellent for execution. Smart routing across pools is the killer feature — it made our tiny-liquidity pool viable for arbitrage. The main pain points are around Permit2 signature handling and some HTTP status code inconsistencies. Would strongly recommend adding quote expiration timestamps and a lighter price-check endpoint for high-frequency polling use cases.
