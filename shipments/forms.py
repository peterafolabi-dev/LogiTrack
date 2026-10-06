from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from .models import Profile, Shipment, StatusUpdate


class ProfileSettingsForm(forms.ModelForm):
    timezone = forms.ChoiceField(
        choices=[
            ("UTC", "UTC"),
            ("America/Chicago", "America/Chicago (CST)"),
            ("America/New_York", "America/New_York (EST)"),
            ("America/Los_Angeles", "America/Los_Angeles (PST)"),
            ("Europe/London", "Europe/London (GMT)"),
        ]
    )
    distance_unit = forms.ChoiceField(choices=[("miles", "Miles (Imperial)"), ("kilometers", "Kilometers (Metric)")])
    currency = forms.ChoiceField(choices=[("USD", "USD — US Dollar"), ("EUR", "EUR — Euro"), ("GBP", "GBP — Pound Sterling")])
    webhook_events = forms.MultipleChoiceField(
        required=False,
        choices=[
            ("shipment.created", "shipment.created"),
            ("shipment.in_transit", "shipment.in_transit"),
            ("shipment.delivered", "shipment.delivered"),
            ("shipment.exception", "shipment.exception"),
        ],
    )

    class Meta:
        model = Profile
        fields = ["business_name", "timezone", "distance_unit", "currency", "webhook_url"]
        widgets = {
            "business_name": forms.TextInput(attrs={"autocomplete": "organization"}),
            "webhook_url": forms.URLInput(attrs={"placeholder": "https://api.example.com/webhooks"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["business_name"].required = True
        if self.instance and self.instance.pk and not self.is_bound:
            self.initial["webhook_events"] = self.instance.webhook_events

    def save(self, commit=True):
        profile = super().save(commit=False)
        profile.webhook_events = self.cleaned_data.get("webhook_events", [])
        if commit:
            profile.save()
        return profile

class SignUpForm(forms.Form):
    business_name = forms.CharField(max_length=120, label="Company name")
    email = forms.EmailField(max_length=150, label="Work email")
    password = forms.CharField(
        label="Create password",
        strip=False,
        widget=forms.PasswordInput,
    )

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        user_model = get_user_model()
        if user_model.objects.filter(email__iexact=email).exists():
            raise ValidationError("An account with this email already exists.")
        if user_model.objects.filter(username__iexact=email).exists():
            raise ValidationError("This email address is already in use.")
        return email

    def clean_password(self):
        password = self.cleaned_data["password"]
        if not any(character.isdigit() for character in password):
            raise ValidationError("Add at least one number.")
        if not any(not character.isalnum() for character in password):
            raise ValidationError("Add at least one symbol.")
        user = get_user_model()(username=self.cleaned_data.get("email", ""))
        validate_password(password, user=user)
        return password

    def save(self):
        user_model = get_user_model()
        email = self.cleaned_data["email"]
        user = user_model.objects.create_user(
            username=email,
            email=email,
            password=self.cleaned_data["password"],
        )
        profile, _ = Profile.objects.get_or_create(user=user)
        profile.business_name = self.cleaned_data["business_name"]
        profile.save()
        return user


class ShipmentForm(forms.ModelForm):
    carrier = forms.ChoiceField(
        choices=[
            ("In-house fleet", "In-House Fleet"),
            ("FedEx Express", "FedEx Express"),
            ("DHL Global", "DHL Global"),
            ("UPS Freight", "UPS Freight"),
            ("FedEx", "FedEx"),
            ("DHL", "DHL"),
        ]
    )

    class Meta:
        model = Shipment
        fields = [
            "recipient_name",
            "recipient_phone",
            "origin",
            "destination",
            "carrier",
            "estimated_delivery",
            "description",
        ]
        widgets = {
            "recipient_name": forms.TextInput(attrs={"placeholder": "Recipient name"}),
            "recipient_phone": forms.TextInput(attrs={"placeholder": "+1 (555) 123-4567"}),
            "origin": forms.TextInput(attrs={"placeholder": "Hub 04 — Chicago, IL"}),
            "destination": forms.TextInput(attrs={"placeholder": "Delivery address"}),
            "estimated_delivery": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "description": forms.Textarea(attrs={"rows": 4, "placeholder": "Special instructions, gate codes, or handling notes"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        carrier_choices = list(self.fields["carrier"].choices)
        current_carrier = self.instance.carrier if self.instance and self.instance.pk else ""
        if current_carrier and current_carrier not in dict(carrier_choices):
            carrier_choices.append((current_carrier, current_carrier))
        self.fields["carrier"].choices = carrier_choices

        for field in self.fields.values():
            field.widget.attrs.setdefault(
                "class",
                "w-full rounded-lg border border-zinc-300 bg-white px-3 py-2.5 text-sm text-zinc-900 outline-none transition duration-200 placeholder:text-zinc-400 focus:border-zinc-900 focus:ring-2 focus:ring-zinc-900",
            )
        self.fields["description"].widget.attrs["class"] += " resize-y"


class ShipmentStatusForm(forms.ModelForm):
    class Meta:
        model = StatusUpdate
        fields = ["status", "location", "note"]
        widgets = {
            "location": forms.TextInput(attrs={"placeholder": "Current location"}),
            "note": forms.Textarea(attrs={"rows": 3, "placeholder": "Status update details"}),
        }

    def __init__(self, shipment, *args, **kwargs):
        self.shipment = shipment
        super().__init__(*args, **kwargs)
        valid = shipment.get_next_statuses()
        self.fields["status"].choices = [(choice, label) for choice, label in Shipment.STATUS_CHOICES if choice in valid]

    def clean_status(self):
        status = self.cleaned_data["status"]
        if not self.shipment.can_transition(self.shipment.status, status):
            raise forms.ValidationError("This status change is not allowed.")
        return status
