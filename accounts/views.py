import secrets
import string

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .gmail_send import GmailUnavailable, send_email


@login_required
def profile(request):
    return render(request, "accounts/profile.html", {"profile_user": request.user})


def _new_password(length=10):
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def forgot_password(request):
    """Email a new temporary password to a registered, active user."""
    sent = False
    error = ""
    if request.method == "POST":
        email = request.POST.get("email", "").strip().lower()
        user = get_user_model().objects.filter(email__iexact=email, is_active=True).first()
        if not user:
            error = "No account found with this email. Please check the address or ask your admin."
        else:
            new_pw = _new_password()
            body = (
                f"Hi {user.display_name},\n\n"
                f"Your new password for Fighter Bull's is:\n\n    {new_pw}\n\n"
                "Please sign in with it, then change it from your profile.\n\n"
                "If you didn't request this, contact your admin.\n"
            )
            try:
                send_email(user.email, "Your new Fighter Bull's password", body)
            except GmailUnavailable:
                error = "Password email isn't available right now. Please contact your admin."
            except Exception:
                error = "Couldn't send the email right now. Please try again or contact your admin."
            else:
                # Only change the password once the email actually went out.
                user.set_password(new_pw)
                user.save(update_fields=["password"])
                sent = True
    return render(request, "accounts/forgot_password.html", {"sent": sent, "error": error})