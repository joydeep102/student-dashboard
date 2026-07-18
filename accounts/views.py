import logging
import secrets
import string

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.messages.views import SuccessMessageMixin
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy

from . import google_config
from .forms import EmailAuthenticationForm
from .gmail_send import GmailUnavailable, send_email

log = logging.getLogger(__name__)


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
                log.warning("Forgot-password: Gmail not connected")
                error = "Password email isn't available right now. Please contact your admin."
            except Exception:
                log.exception("Forgot-password: Gmail send failed")
                error = "Couldn't send the email right now. Please try again or contact your admin."
            else:
                # Only change the password once the email actually went out.
                user.set_password(new_pw)
                user.save(update_fields=["password"])
                sent = True
    return render(request, "accounts/forgot_password.html", {"sent": sent, "error": error})


MAX_GOOGLE_CLIENTS = 5


class LoginView(auth_views.LoginView):
    """Login page. Resolves the Google button per-request so it reflects the
    live client assignment in secrets/google_clients.json (an import-time
    setting would miss clients added later from the admin page)."""

    template_name = "accounts/login.html"
    redirect_authenticated_user = True
    authentication_form = EmailAuthenticationForm

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["google_enabled"] = google_config.is_service_enabled("login")
        return ctx


class PasswordChangeView(SuccessMessageMixin, auth_views.PasswordChangeView):
    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("accounts:profile")
    success_message = "Your password was changed successfully."


@staff_member_required
def google_settings(request):
    """Admin page to manage one or more Google OAuth clients and assign which
    services (login, calendar/meet, youtube, gmail) each one serves."""
    clients, from_env = google_config.load_clients()
    redirect_uri = request.build_absolute_uri(reverse("accounts:google_callback"))

    if request.method == "POST" and not from_env:
        new = []
        for i in range(MAX_GOOGLE_CLIENTS):
            cid = request.POST.get(f"cid_{i}", "").strip()
            if not cid:
                continue
            csec = request.POST.get(f"csec_{i}", "").strip()
            if not csec and i < len(clients):
                csec = clients[i].get("client_secret", "")  # keep existing secret
            new.append({
                "client_id": cid,
                "client_secret": csec,
                "redirect_uri": (request.POST.get(f"ruri_{i}", "").strip() or redirect_uri),
                "services": request.POST.getlist(f"svc_{i}"),
            })
        google_config.save_clients(new)
        messages.success(request, "Google API credentials saved.")
        return redirect("accounts:google_settings")

    rows = []
    for i in range(MAX_GOOGLE_CLIENTS):
        c = clients[i] if i < len(clients) else {}
        rows.append({
            "i": i,
            "client_id": c.get("client_id", ""),
            "has_secret": bool(c.get("client_secret")),
            "services": c.get("services", []),
        })

    from classroom.google_meet import is_configured as calendar_ok
    from trainers.youtube import is_configured as youtube_ok
    from .gmail_send import is_configured as gmail_ok

    return render(
        request,
        "accounts/google_settings.html",
        {
            "rows": rows,
            "services": google_config.SERVICES,
            "redirect_uri": redirect_uri,
            "from_env": from_env,
            "status": {
                "login": google_config.is_service_enabled("login"),
                "calendar": calendar_ok(),
                "youtube": youtube_ok(),
                "gmail": gmail_ok(),
            },
        },
    )