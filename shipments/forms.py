import base64
import secrets

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.utils import timezone

from .models import FAILURE_REASON_CHOICES, Profile, Shipment, StatusUpdate

MAX_SHIPMENT_IMPORT_BYTES = 5 * 1024 * 1024


class ShipmentImportUploadForm(forms.Form):
    csv_file = forms.FileField(label="CSV manifest")

    def clean_csv_file(self):
        uploaded_file = self.cleaned_data["csv_file"]
        if not uploaded_file.name.lower().endswith(".csv"):
            raise ValidationError("Upload a .csv file.")
        if uploaded_file.size > MAX_SHIPMENT_IMPORT_BYTES:
            raise ValidationError("The CSV file must be 5 MB or smaller.")
        return uploaded_file


class ShipmentImportRowForm(forms.Form):
    customer_reference = forms.CharField(max_length=100, required=False, strip=True)
    recipient_name = forms.CharField(max_length=120, strip=True)
    recipient_phone = forms.CharField(max_length=30, strip=True)
    recipient_email = forms.EmailField(max_length=254, required=False)
    origin = forms.CharField(max_length=160, strip=True)
    destination = forms.CharField(max_length=160, strip=True)
    carrier = forms.CharField(max_length=80, required=False, strip=True)
    estimated_delivery = forms.DateTimeField(required=False)
    description = forms.CharField(required=False, strip=True, widget=forms.Textarea)

    def clean_carrier(self):
        return self.cleaned_data.get("carrier") or "In-house fleet"


class DeliveryPreferenceForm(forms.Form):
    delivery_instructions = forms.CharField(
        label="Where should we leave the shipment?",
        max_length=500,
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "autocomplete": "off"}),
    )
    requested_delivery_date = forms.DateField(
        label="Request another delivery date",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    def clean_requested_delivery_date(self):
        requested_date = self.cleaned_data.get("requested_delivery_date")
        if requested_date:
            today = timezone.localdate()
            if requested_date <= today:
                raise ValidationError("Choose a date after today.")
            if requested_date > today + timezone.timedelta(days=30):
                raise ValidationError("Choose a date within the next 30 days.")
        return requested_date

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get("delivery_instructions") and not cleaned_data.get("requested_delivery_date"):
            raise ValidationError("Add delivery instructions or request another delivery date.")
        return cleaned_data


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
    webhook_secret = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"readonly": "readonly", "class": "font-mono text-xs bg-zinc-100"}),
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
        if self.instance and self.instance.pk:
            business = self.instance.get_or_create_business()
            if not self.is_bound:
                self.initial["webhook_events"] = business.webhook_events or self.instance.webhook_events
                self.initial["webhook_secret"] = business.webhook_secret or self.instance.webhook_secret
                self.initial["webhook_url"] = business.webhook_url or self.instance.webhook_url

    def save(self, commit=True):
        profile = super().save(commit=False)
        profile.webhook_events = self.cleaned_data.get("webhook_events", [])
        business = profile.get_or_create_business()
        business.name = profile.business_name
        business.webhook_url = profile.webhook_url
        business.webhook_events = profile.webhook_events
        business.save()
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
        profile.get_or_create_business()
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
            "recipient_email",
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
    delivery_pin = forms.CharField(
        required=False,
        max_length=10,
        widget=forms.TextInput(attrs={"placeholder": "Enter 4-digit recipient PIN", "maxlength": "4"}),
    )
    failure_reason = forms.ChoiceField(
        choices=[("", "-- Select Failure Reason --")] + FAILURE_REASON_CHOICES,
        required=False,
    )
    recipient_signature_data = forms.CharField(
        required=False,
        widget=forms.HiddenInput(),
    )
    delivery_photo = forms.ImageField(
        required=False,
        widget=forms.FileInput(attrs={"accept": "image/*", "capture": "environment"}),
    )
    delivery_lat = forms.DecimalField(
        required=False,
        max_digits=9,
        decimal_places=6,
        widget=forms.HiddenInput(),
    )
    delivery_lng = forms.DecimalField(
        required=False,
        max_digits=9,
        decimal_places=6,
        widget=forms.HiddenInput(),
    )

    class Meta:
        model = StatusUpdate
        fields = [
            "status",
            "location",
            "note",
            "delivery_photo",
            "failure_reason",
            "delivery_lat",
            "delivery_lng",
        ]
        widgets = {
            "location": forms.TextInput(attrs={"placeholder": "Current terminal / checkpoint"}),
            "note": forms.Textarea(attrs={"rows": 3, "placeholder": "Status update details or driver notes"}),
        }

    def __init__(self, shipment, *args, **kwargs):
        self.shipment = shipment
        super().__init__(*args, **kwargs)
        valid = shipment.get_next_statuses()
        self.fields["status"].choices = [(choice, label) for choice, label in Shipment.STATUS_CHOICES if choice in valid]

        base_class = "w-full rounded-lg border border-zinc-300 bg-white px-3 py-2.5 text-sm text-zinc-900 outline-none transition duration-200 placeholder:text-zinc-400 focus:border-zinc-900 focus:ring-2 focus:ring-zinc-900"
        for name, field in self.fields.items():
            if not isinstance(field.widget, forms.HiddenInput) and not isinstance(field.widget, forms.FileInput):
                field.widget.attrs.setdefault("class", base_class)

    def clean_status(self):
        status = self.cleaned_data["status"]
        if not self.shipment.can_transition(self.shipment.status, status):
            raise forms.ValidationError("This status change is not allowed.")
        return status

    def clean(self):
        cleaned_data = super().clean()
        status = cleaned_data.get("status")

        if status == "delivered":
            pin = cleaned_data.get("delivery_pin", "").strip()
            if self.shipment.delivery_pin and not pin:
                self.add_error("delivery_pin", "4-digit delivery PIN is required to confirm delivery handover.")
            elif self.shipment.delivery_pin and not self.shipment.verify_delivery_pin(pin):
                self.add_error("delivery_pin", "Invalid delivery PIN. Please verify with the recipient.")

        elif status == "failed":
            reason = cleaned_data.get("failure_reason", "").strip()
            if not reason:
                self.add_error("failure_reason", "Please select a specific exception reason for delivery failure.")

        return cleaned_data

    def get_signature_file(self):
        sig_data = self.cleaned_data.get("recipient_signature_data", "").strip()
        if not sig_data or not sig_data.startswith("data:image"):
            return None
        try:
            format_meta, img_str = sig_data.split(";base64,")
            ext = "png"
            if "jpeg" in format_meta or "jpg" in format_meta:
                ext = "jpg"
            data = base64.b64decode(img_str)
            filename = f"sig_{self.shipment.tracking_number}_{secrets.token_hex(4)}.{ext}"
            return ContentFile(data, name=filename)
        except Exception:
            return None
