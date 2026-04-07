from django import forms
from django.contrib.auth.forms import AuthenticationForm

from superadmin.models import Restaurant


class PortalAuthenticationForm(AuthenticationForm):
    username = forms.CharField(
        label="User name",
        widget=forms.TextInput(attrs={"class": "t-input", "autofocus": True, "autocomplete": "username"}),
    )
    password = forms.CharField(
        label="Password",
        strip=False,
        widget=forms.PasswordInput(attrs={"class": "t-input", "autocomplete": "current-password"}),
    )


class RestaurantPortalForm(forms.ModelForm):
    class Meta:
        model = Restaurant
        fields = ["name", "phone", "address"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "t-input"}),
            "phone": forms.TextInput(attrs={"class": "t-input"}),
            "address": forms.Textarea(attrs={"class": "t-input t-textarea", "rows": 4}),
        }
