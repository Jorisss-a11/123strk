"""Execution module — Uniswap Trading API swaps + HyperLiquid market orders."""

import time
import requests
from web3 import Web3
from eth_account import Account
from eth_account.messages import encode_typed_data
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
import config

LINK_DECIMALS = 18
USDC_DECIMALS = 6


class Executor:
    def __init__(self):
        self.w3 = Web3(Web3.HTTPProvider(config.QUICKNODE_HTTP))
        self.account = Account.from_key(config.PRIVATE_KEY)
        self.wallet_address = self.account.address

        # Uniswap Trading API
        self.uni_api_url = config.UNISWAP_API_URL
        self.uni_headers = {
            "x-api-key": config.UNISWAP_API_KEY,
            "Content-Type": "application/json",
        }

        # HyperLiquid
        self.hl_info = Info(config.HL_API_URL, skip_ws=True)
        self.hl_exchange = Exchange(
            Account.from_key(config.HL_PRIVATE_KEY),
            config.HL_API_URL,
        )

    def _uni_post(self, endpoint: str, payload: dict) -> dict:
        """POST to Uniswap Trading API."""
        url = f"{self.uni_api_url}/{endpoint}"
        resp = requests.post(url, json=payload, headers=self.uni_headers, timeout=15)
        if resp.status_code != 200:
            print(f"[Uniswap API] {endpoint} failed ({resp.status_code}): {resp.text[:300]}")
            resp.raise_for_status()
        return resp.json()

    def _check_approval(self, token: str, amount_raw: int) -> bool:
        """Check and execute token approval if needed via Uniswap API."""
        data = self._uni_post("check_approval", {
            "walletAddress": self.wallet_address,
            "token": token,
            "amount": str(amount_raw),
            "chainId": 10,
            "includeGasInfo": True,
        })

        approval_tx = data.get("approval")
        if approval_tx is None:
            print("[Uniswap API] Token already approved")
            return True

        print("[Uniswap API] Sending approval tx...")
        tx = {
            "from": self.wallet_address,
            "to": Web3.to_checksum_address(approval_tx["to"]),
            "data": approval_tx["data"],
            "value": int(approval_tx.get("value", "0x0"), 16),
            "chainId": 10,
            "nonce": self.w3.eth.get_transaction_count(self.wallet_address),
            "gas": int(approval_tx.get("gasLimit", "100000")),
            "gasPrice": self.w3.eth.gas_price,
        }
        signed = self.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
        print(f"[Uniswap API] Approval tx: {tx_hash.hex()} (status={receipt['status']})")
        time.sleep(1)
        return receipt["status"] == 1

    def _get_quote(self, token_in: str, token_out: str, amount_raw: int) -> dict:
        """Get a swap quote from Uniswap Trading API."""
        payload = {
            "type": "EXACT_INPUT",
            "amount": str(amount_raw),
            "tokenIn": token_in,
            "tokenOut": token_out,
            "tokenInChainId": 10,
            "tokenOutChainId": 10,
            "swapper": self.wallet_address,
            "slippageTolerance": config.SLIPPAGE_TOLERANCE,
        }
        return self._uni_post("quote", payload)

    def _sign_permit2(self, permit_data: dict) -> str:
        """Sign Permit2 EIP-712 typed data."""
        domain = permit_data["domain"]
        types = permit_data["types"]
        values = permit_data["values"]

        # eth_account's encode_typed_data expects specific format
        signable = encode_typed_data(
            domain_data=domain,
            message_types=types,
            message_data=values,
        )
        signed = self.account.sign_message(signable)
        return "0x" + signed.signature.hex()

    def _build_and_send_swap(self, quote_response: dict, signature: str) -> dict:
        """Build swap tx via API and broadcast it."""
        payload = {
            "quote": quote_response["quote"],
            "simulateTransaction": True,
        }
        if signature and signature != "0x":
            payload["signature"] = signature
        if quote_response.get("permitData"):
            payload["permitData"] = quote_response["permitData"]

        swap_data = self._uni_post("swap", payload)
        swap_tx = swap_data.get("swap")
        if not swap_tx:
            return {"success": False, "error": f"No swap tx in response: {swap_data}"}

        tx = {
            "from": self.wallet_address,
            "to": Web3.to_checksum_address(swap_tx["to"]),
            "data": swap_tx["data"],
            "value": int(swap_tx.get("value", "0x0"), 16),
            "chainId": 10,
            "nonce": self.w3.eth.get_transaction_count(self.wallet_address),
            "gas": int(swap_tx.get("gasLimit", "300000")),
            "gasPrice": self.w3.eth.gas_price,
        }
        signed = self.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        print(f"[Uniswap API] Swap tx sent: {tx_hash.hex()}")

        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
        print(f"[Uniswap API] Swap confirmed: status={receipt['status']}, gas={receipt['gasUsed']}")

        return {
            "success": receipt["status"] == 1,
            "tx_hash": tx_hash.hex(),
            "gas_used": receipt["gasUsed"],
        }

    def uniswap_swap(self, buy_link: bool, amount_in_usd: float, min_amount_out: float = 0) -> dict:
        """Execute a swap via Uniswap Trading API.

        Args:
            buy_link: True = USDC -> LINK, False = LINK -> USDC
            amount_in_usd: Trade size in USD (or LINK amount if selling)
            min_amount_out: Unused (API handles slippage via slippageTolerance)

        Returns:
            {"success": bool, "tx_hash": str, ...}
        """
        if buy_link:
            token_in = config.USDC_ADDRESS
            token_out = config.LINK_ADDRESS
            amount_raw = int(amount_in_usd * (10**USDC_DECIMALS))
        else:
            token_in = config.LINK_ADDRESS
            token_out = config.USDC_ADDRESS
            amount_raw = int(amount_in_usd * (10**LINK_DECIMALS))

        try:
            # Step 1: Check approval FIRST (so quote stays fresh)
            if not self._check_approval(token_in, amount_raw):
                return {"success": False, "tx_hash": "", "error": "Approval failed"}

            # Step 2-4: Quote → sign → swap as fast as possible (quote expires ~30s)
            print(f"[Uniswap API] Getting quote...")
            quote_resp = self._get_quote(token_in, token_out, amount_raw)
            routing = quote_resp.get("routing", "CLASSIC")
            print(f"[Uniswap API] Routing: {routing}")

            signature = "0x"
            permit_data = quote_resp.get("permitData")
            if permit_data:
                print(f"[Uniswap API] Signing Permit2...")
                signature = self._sign_permit2(permit_data)

            result = self._build_and_send_swap(quote_resp, signature)
            return result

        except Exception as e:
            return {"success": False, "tx_hash": "", "error": str(e)}

    def hl_market_order(self, is_buy: bool, size_usd: float, current_price: float) -> dict:
        """Place a market order on HyperLiquid."""
        meta = self.hl_info.meta()
        sz_decimals = 0
        for asset in meta["universe"]:
            if asset["name"] == "LINK":
                sz_decimals = asset["szDecimals"]
                break

        size_link = round(size_usd / current_price, sz_decimals)
        if size_link == 0:
            return {"success": False, "error": "Size rounds to 0"}

        print(f"[HL] Placing {'BUY' if is_buy else 'SELL'} market order: {size_link} LINK")

        try:
            result = self.hl_exchange.market_open(
                "LINK",
                is_buy=is_buy,
                sz=size_link,
                slippage=config.SLIPPAGE_TOLERANCE,
            )
            print(f"[HL] Order result: {result}")
            success = result.get("status") == "ok"
            return {"success": success, "response": result, "size_link": size_link}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def hl_market_close(self, size_link: float) -> dict:
        """Close an HL position."""
        try:
            result = self.hl_exchange.market_close("LINK", sz=size_link)
            print(f"[HL] Close result: {result}")
            return {"success": result.get("status") == "ok", "response": result}
        except Exception as e:
            return {"success": False, "error": str(e)}
