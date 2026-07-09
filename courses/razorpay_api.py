"""Minimal Razorpay client over plain HTTPS (no SDK dependency).

We only need three things from Razorpay — create an order, verify the checkout
callback signature, and verify the webhook signature — all of which are a small
amount of stdlib code. Avoiding the official SDK keeps the dependency tree clean
(the SDK imports the now-removed ``pkg_resources``).

All calls read credentials from settings; ``RAZORPAY_ENABLED`` gates whether the
online option is offered at all.
"""

import base64
import hashlib
import hmac
import json
import urllib.request

from django.conf import settings

API_BASE = "https://api.razorpay.com/v1"


def _auth_header():
    raw = f"{settings.RAZORPAY_KEY_ID}:{settings.RAZORPAY_KEY_SECRET}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def create_order(amount_paise, receipt, notes=None):
    """Create a Razorpay order and return the parsed response dict.

    ``amount_paise`` is the charge in the smallest currency unit (INR paise).
    Raises urllib.error.HTTPError / URLError on failure — callers handle it.
    """
    payload = json.dumps(
        {
            "amount": int(amount_paise),
            "currency": "INR",
            "receipt": receipt[:40],
            "payment_capture": 1,
            "notes": notes or {},
        }
    ).encode()
    req = urllib.request.Request(
        f"{API_BASE}/orders",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": _auth_header()},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 (fixed host)
        return json.loads(resp.read().decode())


def verify_checkout_signature(order_id, payment_id, signature):
    """Verify the signature returned to the browser by Razorpay Checkout."""
    if not (order_id and payment_id and signature):
        return False
    msg = f"{order_id}|{payment_id}".encode()
    expected = hmac.new(
        settings.RAZORPAY_KEY_SECRET.encode(), msg, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def verify_webhook_signature(raw_body, signature):
    """Verify the ``X-Razorpay-Signature`` header on a webhook POST."""
    secret = settings.RAZORPAY_WEBHOOK_SECRET
    if not (secret and signature):
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
