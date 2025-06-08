from django import forms

from .models import User


class AdminRegisterForm(forms.ModelForm):
    password1 = forms.CharField(label="Password 1", widget=forms.PasswordInput)
    confirm_password1 = forms.CharField(label="Confirm Password 1", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Password 2", widget=forms.PasswordInput)
    confirm_password2 = forms.CharField(label="Confirm Password 2", widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ("email",)

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("password1") != cleaned_data.get("confirm_password1"):
            raise forms.ValidationError("Password 1 and Confirm Password 1 do not match.")
        if cleaned_data.get("password2") != cleaned_data.get("confirm_password2"):
            raise forms.ValidationError("Password 2 and Confirm Password 2 do not match.")
        if cleaned_data.get("password1") == cleaned_data.get("password2"):
            raise forms.ValidationError("Password 1 and Password 2 must be different.")
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        user.admin_password2 = self.cleaned_data["password2"]
        user.is_admin = True
        user.is_staff = True
        if commit:
            user.save()
        return user

class DualPasswordAdminLoginForm(forms.Form):
    email = forms.EmailField()
    password1 = forms.CharField(widget=forms.PasswordInput)
    password2 = forms.CharField(widget=forms.PasswordInput)

    def clean(self):
        from django.contrib.auth import authenticate
        cleaned_data = super().clean()
        email = cleaned_data.get("email")
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")

        user = authenticate(username=email, password=password1)
        if not user or not user.is_admin:
            raise forms.ValidationError("Invalid login credentials.")
        if user.admin_password2 != password2:
            raise forms.ValidationError("Second password is incorrect.")

        cleaned_data["user"] = user
        return cleaned_data
