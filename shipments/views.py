import json
import csv
from urllib.parse import urlsplit

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.core.exceptions import ValidationError
from django import forms
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import ProfileSettingsForm, ShipmentForm, ShipmentStatusForm, SignUpForm
from .models import Shipment, STATUS_CHOICES


def landing(request):
    return render(request, "landing.html")


def signup_view(request):
    if request.method == "POST":
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, "Account created successfully.")
            return redirect("dashboard")
    else:
        form = SignUpForm()
    return render(request, "auth/signup.html", {"form": form})


def login_view(request):
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password")
        if "@" in username:
            from django.contrib.auth import get_user_model

            account = get_user_model().objects.filter(email__iexact=username).first()
            if account:
                username = account.get_username()
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            request.session.set_expiry(60 * 60 * 24 * 30 if request.POST.get("remember_device") else 0)
            return redirect("dashboard")
        messages.error(request, "Invalid username or password.")
    return render(request, "auth/login.html")


@login_required
def logout_view(request):
    logout(request)
    return redirect("landing")


@login_required
def dashboard(request):
    queryset = Shipment.objects.filter(user=request.user)
    date_range = request.GET.get("range", "24h")
    if date_range == "today":
        queryset = queryset.filter(created_at__date=timezone.localdate())
    elif date_range == "24h":
        queryset = queryset.filter(created_at__gte=timezone.now() - timezone.timedelta(hours=24))
    else:
        date_range = "all"
    counts = queryset.values("status").annotate(total=Count("id"))
    status_counts = {entry["status"]: entry["total"] for entry in counts}
    latest_shipments = queryset.select_related("user")[:8]
    status_counts["all"] = queryset.count()
    return render(
        request,
        "dashboard.html",
        {
            "status_counts": status_counts,
            "latest_shipments": latest_shipments,
            "shipment_status_choices": STATUS_CHOICES,
            "organization": getattr(getattr(request.user, "profile", None), "business_name", ""),
            "date_range": date_range,
        },
    )


@login_required
def shipments_list(request):
    queryset = Shipment.objects.filter(user=request.user)
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    carrier = request.GET.get("carrier", "").strip()
    date_range = request.GET.get("range", "").strip()
    if query:
        queryset = queryset.filter(
            Q(recipient_name__icontains=query)
            | Q(tracking_number__icontains=query)
            | Q(destination__icontains=query)
            | Q(origin__icontains=query)
            | Q(carrier__icontains=query)
        )
    if status and status in dict(STATUS_CHOICES):
        queryset = queryset.filter(status=status)
    if carrier:
        queryset = queryset.filter(carrier=carrier)
    if date_range == "24h":
        queryset = queryset.filter(created_at__gte=timezone.now() - timezone.timedelta(hours=24))
    elif date_range == "7d":
        queryset = queryset.filter(created_at__gte=timezone.now() - timezone.timedelta(days=7))

    if request.GET.get("export") in {"csv", "json"}:
        rows = queryset.order_by("-created_at")
        if request.GET["export"] == "json":
            response = JsonResponse(
                [
                    {
                        "tracking_number": shipment.tracking_number,
                        "recipient": shipment.recipient_name,
                        "origin": shipment.origin,
                        "destination": shipment.destination,
                        "status": shipment.status,
                        "carrier": shipment.carrier,
                        "estimated_delivery": shipment.estimated_delivery.isoformat() if shipment.estimated_delivery else None,
                    }
                    for shipment in rows
                ],
                safe=False,
            )
            response["Content-Disposition"] = 'attachment; filename="logitrack-manifest.json"'
            return response
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="logitrack-manifest.csv"'
        writer = csv.writer(response)
        writer.writerow(["Tracking ID", "Recipient", "Origin", "Destination", "Status", "Carrier", "Estimated delivery"])
        for shipment in rows:
            writer.writerow([
                shipment.tracking_number,
                shipment.recipient_name,
                shipment.origin,
                shipment.destination,
                shipment.get_status_display(),
                shipment.carrier,
                shipment.estimated_delivery.isoformat() if shipment.estimated_delivery else "",
            ])
        return response

    status_counts = {
        entry["status"]: entry["total"]
        for entry in Shipment.objects.filter(user=request.user).values("status").annotate(total=Count("id"))
    }
    paginator = Paginator(queryset.select_related("user"), 25)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)
    return render(
        request,
        "shipments/list.html",
        {
            "page_obj": page_obj,
            "query": query,
            "status": status,
            "carrier": carrier,
            "date_range": date_range,
            "status_counts": status_counts,
            "shipment_status_choices": STATUS_CHOICES,
            "carriers": Shipment.objects.filter(user=request.user).values_list("carrier", flat=True).distinct().order_by("carrier"),
            "total_count": Shipment.objects.filter(user=request.user).count(),
        },
    )


@login_required
@require_POST
def populate_demo_telemetry(request):
    samples = [
        ("pending", "Morgan Reed", "Seattle, WA", "Portland, OR", "In-house fleet"),
        ("picked_up", "Avery Chen", "San Francisco, CA", "Sacramento, CA", "FedEx"),
        ("in_transit", "Jordan Blake", "Austin, TX", "Denver, CO", "DHL"),
        ("out_for_delivery", "Riley Morgan", "Boston, MA", "New York, NY", "In-house fleet"),
        ("delivered", "Casey Taylor", "Chicago, IL", "Austin, TX", "FedEx"),
        ("failed", "Sam Rivera", "Phoenix, AZ", "Las Vegas, NV", "DHL"),
    ]
    created_count = 0
    for status, recipient, origin, destination, carrier in samples:
        shipment = Shipment.objects.create(
            user=request.user,
            recipient_name=recipient,
            recipient_phone="+1 555 010 2040",
            origin=origin,
            destination=destination,
            carrier=carrier,
            status=status,
        )
        created_count += 1
    messages.success(request, f"{created_count} sample shipments added to your fleet.")
    return redirect(request.POST.get("next") or "dashboard")


@login_required
def shipment_detail(request, pk):
    shipment = get_object_or_404(Shipment, pk=pk, user=request.user)
    status_form = ShipmentStatusForm(shipment)
    if request.method == "POST":
        status_form = ShipmentStatusForm(shipment, request.POST)
        if status_form.is_valid():
            shipment.transition_to(
                status_form.cleaned_data["status"],
                location=status_form.cleaned_data.get("location", ""),
                note=status_form.cleaned_data.get("note", ""),
            )
            messages.success(request, "Shipment status updated.")
            return redirect("shipment_detail", pk=shipment.pk)
    return render(request, "shipments/detail.html", {"shipment": shipment, "status_form": status_form})


@login_required
def shipment_edit(request, pk):
    shipment = get_object_or_404(Shipment, pk=pk, user=request.user)
    if request.method == "POST":
        form = ShipmentForm(request.POST, instance=shipment)
        if form.is_valid():
            form.save()
            return redirect("shipment_detail", pk=shipment.pk)
    else:
        form = ShipmentForm(instance=shipment)
    return render(request, "shipments/form.html", {"form": form, "shipment": shipment, "editing": True})


@login_required
def shipment_create(request):
    if request.method == "POST":
        form = ShipmentForm(request.POST)
        if form.is_valid():
            shipment = form.save(commit=False)
            shipment.user = request.user
            shipment.save()
            messages.success(request, "Shipment created successfully.")
            return redirect("shipment_detail", pk=shipment.pk)
    else:
        form = ShipmentForm()
    return render(request, "shipments/form.html", {"form": form, "shipment": None, "editing": False})


@login_required
def profile_view(request):
    profile = request.user.profile
    active_tab = request.GET.get("tab", "general")
    if request.method == "POST":
        active_tab = request.POST.get("tab", "general")
        if active_tab == "security":
            password_form = PasswordChangeForm(request.user, request.POST)
            if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(request, user)
                messages.success(request, "Password updated successfully.")
                return redirect(f"{reverse('profile')}?tab=security")
            return render(request, "profile.html", {
                "active_tab": active_tab,
                "settings_form": ProfileSettingsForm(instance=profile),
                "password_form": password_form,
            })
        if active_tab == "api":
            try:
                endpoint = forms.URLField(required=False).clean(request.POST.get("webhook_url", "").strip())
            except ValidationError:
                messages.error(request, "Enter a valid HTTPS webhook URL.")
                return redirect(f"{reverse('profile')}?tab=api")
            if endpoint and urlsplit(endpoint).scheme != "https":
                messages.error(request, "Webhook endpoints must use HTTPS.")
                return redirect(f"{reverse('profile')}?tab=api")
            allowed_events = {
                "shipment.created",
                "shipment.in_transit",
                "shipment.delivered",
                "shipment.exception",
            }
            events = request.POST.getlist("webhook_events")
            if not set(events).issubset(allowed_events):
                messages.error(request, "Select only supported shipment webhook events.")
                return redirect(f"{reverse('profile')}?tab=api")
            profile.webhook_url = endpoint
            profile.webhook_events = events
            profile.save(update_fields=["webhook_url", "webhook_events"])
            messages.success(request, "Webhook preferences saved. Delivery execution is not enabled in this deployment.")
            return redirect(f"{reverse('profile')}?tab=api")
        settings_form = ProfileSettingsForm(request.POST, instance=profile)
        if settings_form.is_valid():
            profile = settings_form.save(commit=False)
            profile.save()
            messages.success(request, "Organization settings updated successfully.")
            return redirect(f"{reverse('profile')}?tab={active_tab}")
        password_form = PasswordChangeForm(request.user)
    else:
        settings_form = ProfileSettingsForm(instance=profile)
        password_form = PasswordChangeForm(request.user)
    api_form = ProfileSettingsForm(instance=profile)
    return render(request, "profile.html", {
        "active_tab": active_tab,
        "settings_form": settings_form,
        "password_form": password_form,
        "api_form": api_form,
        "organization_id": f"org_{request.user.pk:04d}",
    })


def public_tracking_page(request):
    tracking_number = request.GET.get("tracking_number", "").strip().upper()
    shipment = None
    if tracking_number:
        shipment = Shipment.objects.filter(tracking_number__iexact=tracking_number).prefetch_related("history").first()
        if shipment:
            recent_numbers = request.session.get("recent_tracking_numbers", [])
            recent_numbers = [number for number in recent_numbers if number != shipment.tracking_number]
            request.session["recent_tracking_numbers"] = [shipment.tracking_number, *recent_numbers[:4]]

    recent_numbers = request.session.get("recent_tracking_numbers", [])
    shipments_by_number = Shipment.objects.filter(
        tracking_number__in=recent_numbers
    ).prefetch_related("history")
    shipments_by_number = {item.tracking_number: item for item in shipments_by_number}
    recent_shipments = [
        shipments_by_number[number]
        for number in recent_numbers
        if number in shipments_by_number
    ]
    return render(
        request,
        "public_tracking.html",
        {
            "shipment": shipment,
            "tracking_number": tracking_number,
            "recent_shipments": recent_shipments,
            "shipment_status_choices": STATUS_CHOICES,
        },
    )


def public_tracking_api(request, tracking_number):
    shipment = get_object_or_404(Shipment, tracking_number=tracking_number)
    data = {
        "tracking_number": shipment.tracking_number,
        "status": shipment.status,
        "origin": shipment.origin,
        "destination": shipment.destination,
        "updated_at": shipment.updated_at.isoformat(),
        "history": [
            {
                "status": entry.status,
                "location": entry.location,
                "note": entry.note,
                "created_at": entry.created_at.isoformat(),
            }
            for entry in shipment.history.all()
        ],
    }
    return JsonResponse(data)
