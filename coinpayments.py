"""CoinPayments API v1 client.

Handles transaction creation, status checks, and IPN verification.
Docs: https://www.coinpayments.net/apidoc
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from urllib.parse import urlencode

import httpx

import config

logger = logging.getLogger(__name__)

API_URL = "https://www.coinpayments.net/api.php"

COIN_MAP = {
    "TRX": "TRX",
    "USDT": "USDT.TRC20",
}


def _sign(params: dict) -> str:
    encoded = urlencode(params)
    return hmac.new(
        config.CP_PRIVATE_KEY.encode(),
        encoded.encode(),
        hashlib.sha512,
    ).hexdigest()


async def _call(cmd: str, **kwargs) -> dict:
    params = {
        "version": 1,
        "cmd": cmd,
        "key": config.CP_PUBLIC_KEY,
        "format": "json",
        **kwargs,
    }
    headers = {"HMAC": _sign(params)}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(API_URL, data=params, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    if data.get("error") != "ok":
        raise CoinPaymentsError(data.get("error", "Unknown error"))

    return data.get("result", {})


class CoinPaymentsError(Exception):
    pass


async def create_transaction(
    amount: float,
    currency: str,
    buyer_email: str = "",
    ipn_url: str = "",
    custom: str = "",
) -> dict:
    """Create a payment transaction. Returns deposit address, amount, txn_id, etc."""
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

    result = await _call("create_transaction", **params)
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


async def get_tx_info(txn_id: str) -> dict:
    """Check the status of a transaction."""
    result = await _call("get_tx_info", txid=txn_id)
    return {
        "status": int(result.get("status", -1)),
        "status_text": result.get("status_text", ""),
        "coin": result.get("coin", ""),
        "amount": float(result.get("amountf", 0)),
        "received": float(result.get("receivedf", 0)),
        "recv_confirms": int(result.get("recv_confirms", 0)),
    }


def verify_ipn(hmac_header: str, body: bytes) -> bool:
    """Verify IPN callback authenticity using the IPN secret."""
    expected = hmac.new(
        config.CP_IPN_SECRET.encode(),
        body,
        hashlib.sha512,
    ).hexdigest()
    return hmac.compare_digest(expected, hmac_header)


# IPN status codes from CoinPayments
IPN_STATUS_WAITING = 0
IPN_STATUS_CONFIRMED = 1
IPN_STATUS_QUEUED = 2
IPN_STATUS_COMPLETE = 100
IPN_STATUS_CANCELLED = -1
