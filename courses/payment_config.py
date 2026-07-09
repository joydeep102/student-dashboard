"""Resolve the active payment configuration.

Values entered in the admin :class:`PaymentSettings` singleton take precedence;
blank fields fall back to the environment-based settings. This lets an admin turn
UPI / Razorpay on or off from the admin without a redeploy.
"""

import types

from django.conf import settings


def payment_config():
    row = None
    try:
        from .models import PaymentSettings

        row = PaymentSettings.objects.first()
    except Exception:  # table missing during migrate, etc.
        row = None

    def pick(attr, env_value):
        val = (getattr(row, attr, "") or "") if row else ""
        return val or env_value

    key_id = pick("razorpay_key_id", settings.RAZORPAY_KEY_ID)
    key_secret = pick("razorpay_key_secret", settings.RAZORPAY_KEY_SECRET)
    preview = (
        (row.preview_lessons if row and row.preview_lessons else None)
        or getattr(settings, "PROVISIONAL_PREVIEW_LESSONS", 2)
    )
    return types.SimpleNamespace(
        upi_vpa=pick("upi_vpa", settings.UPI_VPA),
        upi_payee_name=pick("upi_payee_name", settings.UPI_PAYEE_NAME),
        razorpay_key_id=key_id,
        razorpay_key_secret=key_secret,
        razorpay_webhook_secret=pick("razorpay_webhook_secret", settings.RAZORPAY_WEBHOOK_SECRET),
        razorpay_enabled=bool(key_id and key_secret),
        preview_lessons=preview,
    )
