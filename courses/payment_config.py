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
    default_share = (row.default_instructor_share if row else None)
    if default_share is None:
        default_share = 70
    return types.SimpleNamespace(
        upi_vpa=pick("upi_vpa", settings.UPI_VPA),
        upi_payee_name=pick("upi_payee_name", settings.UPI_PAYEE_NAME),
        razorpay_key_id=key_id,
        razorpay_key_secret=key_secret,
        razorpay_webhook_secret=pick("razorpay_webhook_secret", settings.RAZORPAY_WEBHOOK_SECRET),
        razorpay_enabled=bool(key_id and key_secret),
        preview_lessons=preview,
        default_instructor_share=default_share,
    )


def instructor_earnings(instructor):
    """Payout figures for an instructor.

    gross    — sum of their verified (paid) course sales
    share    — their revenue-share % (own override, else platform default)
    payable  — gross × share%
    paid_out — sum of payouts already recorded to them
    balance  — payable − paid_out (what they're still owed)
    """
    from decimal import Decimal

    from django.db.models import Sum

    from .models import CoursePayment, Payout

    gross = (
        CoursePayment.objects.filter(
            course__instructor=instructor, status=CoursePayment.Status.PAID
        ).aggregate(s=Sum("amount"))["s"]
        or Decimal("0")
    )
    share = instructor.payout_share_percent
    if share is None:
        share = payment_config().default_instructor_share
    payable = (gross * Decimal(share) / Decimal(100)).quantize(Decimal("0.01"))
    paid_out = (
        Payout.objects.filter(instructor=instructor, status=Payout.Status.PAID).aggregate(
            s=Sum("amount")
        )["s"]
        or Decimal("0")
    )
    requested = (
        Payout.objects.filter(instructor=instructor, status=Payout.Status.REQUESTED).aggregate(
            s=Sum("amount")
        )["s"]
        or Decimal("0")
    )
    balance = payable - paid_out
    return {
        "gross": gross,
        "share": share,
        "payable": payable,
        "paid_out": paid_out,
        "requested": requested,          # awaiting admin approval
        "balance": balance,              # total still owed (paid subtracted)
        "available": balance - requested,  # can still be requested
    }
