from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm


class EmailAuthenticationForm(AuthenticationForm):
    username = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(attrs={"autofocus": True}),
    )



User = get_user_model()

class DualPasswordAuthenticationForm(AuthenticationForm):
    username = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(attrs={"autofocus": True}),
    )
    second_password = forms.CharField(
        label="Second Password",
        widget=forms.PasswordInput,
        required=False,
    )

    def clean(self):
        cleaned_data = super().clean()
        email = cleaned_data.get("username")
        password = cleaned_data.get("password")  # noqa: F841
        second_password = cleaned_data.get("second_password")

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return cleaned_data  # let normal auth handle the error

        # If second password is set, require it and verify
        if user.is_admin and user.admin_password2:
            if not second_password:
                msg = "Second password is required for this admin user."
                raise forms.ValidationError(msg)
            if not user.check_admin_password2(second_password):
                msg = "Second password is incorrect."
                raise forms.ValidationError(msg)

        return cleaned_data
