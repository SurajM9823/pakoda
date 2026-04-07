from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm

from .models import FiscalYear, Restaurant, RestaurantStaff

User = get_user_model()


class SuperadminAuthenticationForm(AuthenticationForm):
    username = forms.CharField(
        label="Username",
        widget=forms.TextInput(attrs={"class": "form-control", "autofocus": True}),
    )
    password = forms.CharField(
        label="Password",
        strip=False,
        widget=forms.PasswordInput(attrs={"class": "form-control"}),
    )


class RestaurantForm(forms.ModelForm):
    class Meta:
        model = Restaurant
        fields = ["name", "slug", "is_active", "phone", "address"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "slug": forms.TextInput(attrs={"class": "form-control"}),
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "address": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False
        self.fields["slug"].help_text = "Leave blank to auto-generate from name."


class FiscalYearForm(forms.ModelForm):
    class Meta:
        model = FiscalYear
        fields = ["label", "start_date", "end_date", "is_active"]
        widgets = {
            "label": forms.TextInput(attrs={"class": "form-control"}),
            "start_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "end_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class RestaurantStaffForm(forms.Form):
    username = forms.CharField(max_length=150, widget=forms.TextInput(attrs={"class": "form-control"}))
    email = forms.EmailField(required=False, widget=forms.EmailInput(attrs={"class": "form-control"}))
    password1 = forms.CharField(
        label="Password",
        strip=False,
        widget=forms.PasswordInput(attrs={"class": "form-control"}),
    )
    password2 = forms.CharField(
        label="Confirm password",
        strip=False,
        widget=forms.PasswordInput(attrs={"class": "form-control"}),
    )
    role = forms.ChoiceField(
        choices=RestaurantStaff.Role.choices,
        widget=forms.Select(attrs={"class": "form-control"}),
    )

    def clean_username(self):
        u = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=u).exists():
            raise forms.ValidationError("A user with this username already exists.")
        return u

    def clean(self):
        data = super().clean()
        p1 = data.get("password1")
        p2 = data.get("password2")
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError("Passwords do not match.")
        return data


class ActiveRestaurantForm(forms.Form):
    restaurant = forms.ModelChoiceField(
        queryset=Restaurant.objects.filter(is_active=True).order_by("name"),
        required=False,
        empty_label="— All restaurants (no filter) —",
        widget=forms.Select(attrs={"class": "form-control form-control-sm"}),
    )
