from django import forms
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.forms import AuthenticationForm


class EmailAuthenticationForm(AuthenticationForm):
    """Login form that gives a specific reason when sign-in fails:
    unknown email, inactive account, or wrong password."""

    def clean(self):
        email = self.cleaned_data.get("username")  # USERNAME_FIELD is email
        password = self.cleaned_data.get("password")
        if email and password:
            User = get_user_model()
            user = User.objects.filter(email__iexact=email).first()
            if user is None:
                raise forms.ValidationError(
                    "No account found with this email. Please check the address "
                    "or ask your admin to create one.",
                    code="no_user",
                )
            if not user.is_active:
                raise forms.ValidationError(
                    "This account is inactive. Please contact your admin.",
                    code="inactive",
                )
            self.user_cache = authenticate(self.request, username=email, password=password)
            if self.user_cache is None:
                raise forms.ValidationError(
                    "Incorrect password. Please try again.", code="bad_password"
                )
            self.confirm_login_allowed(self.user_cache)
        return self.cleaned_data