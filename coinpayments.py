"""CoinPayments API client with v1 (legacy) and v2 support.

v1 (legacy): POST to https://www.coinpayments.net/api.php, HMAC-SHA512 in header
v2 (current): REST JSON to https://a-api.coinpayments.net/api/v2/, HMAC in X-CoinPayments-Signature

Set config.CP_API_VERSION = 1 or 2 to choose. Default is 1 for backward compat.
v2 is recommended by CoinPayments for new integrations.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx

import config

logger = logging.getLogger(__name__)

V1_API_URL = "https://www.coinpayments.net/api.php"
V2_API_URL = "https://a-api.coinpayments.net/api/v2"

COIN_MAP = {
    "TRX": "TRX",
    "USDT": "USDT.TRC20",
}

# CoinPayments IPN / webhook status codes
# https://a-docs.coinpayments.net/api/migration-guide
IPN_STATUS_CANCELLED = -1   # Cancelled / timed out / refunded
IPN_STATUS_WAITING = 0      # Waiting for funds
IPN_STATUS_CONFIRMED = 1    # Funds received, waiting for confirmations
IPN_STATUS_COMPLETE = 2     # Payment complete
IPN_STATUS_COMPLETE_ALT = 100  # Payment complete (legacy alias)

# CoinPayments charges a network fee on deposits (configurable in your CP account)
CP_NETWORK_FEE_PCT = 0.5


class CoinPaymentsError(Exception):
    pass


def is_payment_complete(status: int) -> bool:
    """True if the IPN status means payment is fully complete and settled."""
    return status >= IPN_STATUS_COMPLETE


def is_payment_pending(status: int) -> bool:
    return status in (IPN_STATUS_WAITING, IPN_STATUS_CONFIRMED)


def is_payment_failed(status: int) -> bool:
    return status < 0


# ---------------------------------------------------------------------------
# v1 API (legacy)
# ---------------------------------------------------------------------------

def _v1_sign(params: dict) -> str:
    encoded = urlencode(params)
    return hmac.new(
        config.CP_PRIVATE_KEY.encode(),
        encoded.encode(),
        hashlib.sha512,
    ).hexdigest()


async def _v1_call(cmd: str, **kwargs) -> dict:
    params = {
        "version": 1,
        "cmd": cmd,
        "key": config.CP_PUBLIC_KEY,
        "format": "json",
        **kwargs,
    }
    headers = {"HMAC": _v1_sign(params)}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(V1_API_URL, data=params, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    if data.get("error") != "ok":
        raise CoinPaymentsError(data.get("error", "Unknown error"))

    return data.get("result", {})


# ---------------------------------------------------------------------------
# v2 API (current, recommended)
# ---------------------------------------------------------------------------

def _v2_sign(method: str, url: str, timestamp: str, body: str) -> str:
    """Generate HMAC signature for v2 API requests.

    Signature = HMAC-SHA256(client_secret, \ufeff + method + url + client_id + timestamp + body)
    The BOM (\ufeff) is prepended per CoinPayments docs.
    """
    bom = "\ufeff"
    msg = f"{bom}{method}{url}{config.CP_CLIENT_ID}{timestamp}{body}"
    return hmac.new(
        config.CP_PRIVATE_KEY.encode(),
        msg.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


async def _v2_call(method: str, path: str, body: dict | None = None) -> dict:
    url = f"{V2_API_URL}{path}"
    timestamp = datetime.now(timezone.utc).isoformat()
    body_str = json.dumps(body) if body else ""

    sig = _v2_sign(method.upper(), url, timestamp, body_str)

    headers = {
        "X-CoinPayments-Client": config.CP_CLIENT_ID,
        "X-CoinPayments-Timestamp": timestamp,
        "X-CoinPayments-Signature": sig,
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        if method.upper() == "POST":
            resp = await client.post(url, content=body_str, headers=headers)
        else:
            resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    return data


# ---------------------------------------------------------------------------
# Unified public API
# ---------------------------------------------------------------------------

async def create_transaction(
    amount: float,
    currency: str,
    buyer_email: str = "",
    ipn_url: str = "",
    custom: str = "",
) -> dict:
    """Create a payment transaction. Returns deposit address, txn_id, etc.

    Uses v1 or v2 depending on config.CP_API_VERSION.
    """
    api_version = getattr(config, "CP_API_VERSION", 1)

    if api_version == 2:
        return await _create_transaction_v2(amount, currency, custom)
    return await _create_transaction_v1(amount, currency, buyer_email, ipn_url, custom)


async def _create_transaction_v1(
    amount: float, currency: str, buyer_email: str, ipn_url: str, custom: str,
) -> dict:
    coin = COIN_MAP.get(currency, currency)
    params = {
        "amount": amount,
        "currency1": coin,
        "currency2": coin,
    }
    if buyer_email:
        params["buyer_email"] = buyer_email
    if ipn_url:
        params["ipn_url"] = ipn_url
    if custom:
        params["custom"] = custom

    result = await _v1_call("create_transaction", **params)
    return {
        "txn_id": result.get("txn_id"),
        "address": result.get("address"),
        "amount": float(result.get("amount", amount)),
        "confirms_needed": result.get("confirms_needed", "1"),
        "timeout": result.get("timeout"),
        "checkout_url": result.get("checkout_url", ""),
        "status_url": result.get("status_url", ""),
        "qrcode_url": result.get("qrcode_url", ""),
    }


async def _create_transaction_v2(amount: float, currency: str, custom: str) -> dict:
    coin = COIN_MAP.get(currency, currency)
    body = {
        "amount": {"currencyId": coin, "value": str(amount)},
        "customData": custom,
    }

    if config.IPN_URL:
        body["notificationUrl"] = config.IPN_URL

    result = await _v2_call("POST", "/merchant/invoices", body)

    return {
        "txn_id": result.get("id", result.get("invoiceId", "")),
        "address": result.get("address", ""),
        "amount": amount,
        "confirms_needed": "1",
        "timeout": result.get("expiry", ""),
        "checkout_url": result.get("checkoutLink", result.get("link", "")),
        "status_url": "",
        "qrcode_url": "",
    }


async def get_tx_info(txn_id: str) -> dict:
    """Check the status of a transaction."""
    api_version = getattr(config, "CP_API_VERSION", 1)

    if api_version == 2:
        result = await _v2_call("GET", f"/merchant/invoices/{txn_id}")
        return {
            "status": _map_v2_status(result.get("status", "")),
            "status_text": result.get("status", ""),
            "coin": result.get("currency", ""),
            "amount": float(result.get("amount", {}).get("value", 0)),
            "received": float(result.get("paidAmount", {}).get("value", 0)),
            "recv_confirms": 0,
        }

    result = await _v1_call("get_tx_info", txid=txn_id)
    return {
        "status": int(result.get("status", -1)),
        "status_text": result.get("status_text", ""),
        "coin": result.get("coin", ""),
        "amount": float(result.get("amountf", 0)),
        "received": float(result.get("receivedf", 0)),
        "recv_confirms": int(result.get("recv_confirms", 0)),
    }


def _map_v2_status(status_str: str) -> int:
    """Map v2 string statuses to v1 integer codes for unified handling."""
    mapping = {
        "new": IPN_STATUS_WAITING,
        "pending": IPN_STATUS_WAITING,
        "confirming": IPN_STATUS_CONFIRMED,
        "paid": IPN_STATUS_COMPLETE,
        "completed": IPN_STATUS_COMPLETE,
        "cancelled": IPN_STATUS_CANCELLED,
        "expired": IPN_STATUS_CANCELLED,
        "refunded": IPN_STATUS_CANCELLED,
    }
    return mapping.get(status_str.lower(), IPN_STATUS_WAITING)


# ---------------------------------------------------------------------------
# IPN / Webhook verification
# ---------------------------------------------------------------------------

def verify_ipn_v1(hmac_header: str, body: bytes) -> bool:
    """Verify v1 IPN callback using IPN secret + HMAC-SHA512."""
    expected = hmac.new(
        config.CP_IPN_SECRET.encode(),
        body,
        hashlib.sha512,
    ).hexdigest()
    return hmac.compare_digest(expected, hmac_header)


def verify_webhook_v2(
    signature: str,
    client_id: str,
    timestamp: str,
    body: bytes,
    url: str,
    method: str = "POST",
) -> bool:
    """Verify v2 webhook using X-CoinPayments-Signature header."""
    bom = "\ufeff"
    msg = f"{bom}{method}{url}{client_id}{timestamp}{body.decode('utf-8')}"
    expected = hmac.new(
        config.CP_PRIVATE_KEY.encode(),
        msg.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def verify_ipn(hmac_header: str, body: bytes) -> bool:
    """Backward-compatible alias for v1 IPN verification."""
    return verify_ipn_v1(hmac_header, body)
