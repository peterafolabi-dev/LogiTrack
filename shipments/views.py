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
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django_ratelimit.decorators import ratelimit

from .forms import (
    ProfileSettingsForm,
    ShipmentForm,
    ShipmentImportUploadForm,
    ShipmentStatusForm,
    SignUpForm,
)
from .models import (
    Business,
    Shipment,
    ShipmentImportBatch,
    StatusUpdate,
    WebhookDeliveryLog,
    STATUS_CHOICES,
)
from .services.labels import generate_thermal_label_pdf


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
    business = request.user.profile.get_or_create_business()
    queryset = Shipment.objects.filter(business=business)
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
            "organization": business.name,
            "date_range": date_range,
        },
    )


@login_required
def shipments_list(request):
    business = request.user.profile.get_or_create_business()
    queryset = Shipment.objects.filter(business=business)
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
        for entry in Shipment.objects.filter(business=business).values("status").annotate(total=Count("id"))
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
            "carriers": Shipment.objects.filter(business=business).values_list("carrier", flat=True).distinct().order_by("carrier"),
            "total_count": Shipment.objects.filter(business=business).count(),
        },
    )


@login_required
@require_POST
def populate_demo_telemetry(request):
    business = request.user.profile.get_or_create_business()
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
            business=business,
            recipient_name=recipient,
            recipient_phone="+1 555 010 2040",
            origin=origin,
            destination=destination,
            carrier=carrier,
            status=status,
            failure_reason="gate_locked" if status == "failed" else "",
        )
        created_count += 1
    messages.success(request, f"{created_count} sample shipments added to your fleet.")
    return redirect(request.POST.get("next") or "dashboard")


@login_required
def shipment_detail(request, pk):
    business = request.user.profile.get_or_create_business()
    shipment = get_object_or_404(Shipment, pk=pk, business=business)
    status_form = ShipmentStatusForm(shipment)

    if request.method == "POST":
        status_form = ShipmentStatusForm(shipment, request.POST, request.FILES)
        if status_form.is_valid():
            try:
                recipient_sig = status_form.get_signature_file()
                delivery_photo = status_form.cleaned_data.get("delivery_photo")
                delivery_lat = status_form.cleaned_data.get("delivery_lat")
                delivery_lng = status_form.cleaned_data.get("delivery_lng")
                delivery_pin = status_form.cleaned_data.get("delivery_pin")
                failure_reason = status_form.cleaned_data.get("failure_reason", "")

                shipment.transition_to(
                    status_form.cleaned_data["status"],
                    location=status_form.cleaned_data.get("location", ""),
                    note=status_form.cleaned_data.get("note", ""),
                    recipient_signature=recipient_sig,
                    delivery_photo=delivery_photo,
                    delivery_lat=delivery_lat,
                    delivery_lng=delivery_lng,
                    delivery_pin=delivery_pin,
                    failure_reason=failure_reason,
                )
                messages.success(request, f"Shipment transition recorded successfully ({shipment.get_status_display()}).")
                return redirect("shipment_detail", pk=shipment.pk)
            except ValidationError as err:
                status_form.add_error(None, err.message if hasattr(err, "message") else str(err))

    return render(
        request,
        "shipments/detail.html",
        {
            "shipment": shipment,
            "status_form": status_form,
        },
    )


@login_required
def shipment_edit(request, pk):
    business = request.user.profile.get_or_create_business()
    shipment = get_object_or_404(Shipment, pk=pk, business=business)
    if request.method == "POST":
        form = ShipmentForm(request.POST, instance=shipment)
        if form.is_valid():
            form.save()
            messages.success(request, "Shipment details updated.")
            return redirect("shipment_detail", pk=shipment.pk)
    else:
        form = ShipmentForm(instance=shipment)
    return render(request, "shipments/form.html", {"form": form, "shipment": shipment, "editing": True})


@login_required
def shipment_create(request):
    business = request.user.profile.get_or_create_business()
    if request.method == "POST":
        form = ShipmentForm(request.POST)
        if form.is_valid():
            shipment = form.save(commit=False)
            shipment.user = request.user
            shipment.business = business
            shipment.save()
            messages.success(request, f"Shipment created successfully. PIN: {shipment.delivery_pin_raw}")
            return redirect("shipment_detail", pk=shipment.pk)
    else:
        form = ShipmentForm()
    return render(request, "shipments/form.html", {"form": form, "shipment": None, "editing": False})


@login_required
def shipment_import_create(request):
    business = request.user.profile.get_or_create_business()
    if request.method == "POST":
        form = ShipmentImportUploadForm(request.POST, request.FILES)
        if form.is_valid():
            batch = ShipmentImportBatch.objects.create(
                business=business,
                user=request.user,
                source_file=form.cleaned_data["csv_file"],
            )
            from .tasks import validate_shipment_import_task

            transaction.on_commit(lambda: validate_shipment_import_task.delay(batch.pk))
            messages.success(request, "CSV uploaded. Validation is running in the background.")
            return redirect("shipment_import_detail", pk=batch.pk)
    else:
        form = ShipmentImportUploadForm()

    recent_imports = ShipmentImportBatch.objects.filter(business=business)[:10]
    return render(
        request,
        "shipments/import.html",
        {"form": form, "recent_imports": recent_imports},
    )


@login_required
def shipment_import_template(request):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="logitrack-shipment-import-template.csv"'
    writer = csv.writer(response)
    writer.writerow([
        "customer_reference",
        "recipient_name",
        "recipient_phone",
        "origin",
        "destination",
        "carrier",
        "estimated_delivery",
        "description",
    ])
    return response


@login_required
def shipment_import_detail(request, pk):
    business = request.user.profile.get_or_create_business()
    batch = get_object_or_404(ShipmentImportBatch, pk=pk, business=business)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "confirm" and batch.status == "ready" and batch.valid_rows:
            with transaction.atomic():
                batch.status = "queued"
                batch.save(update_fields=["status", "updated_at"])
                from .tasks import process_shipment_import_task

                transaction.on_commit(lambda: process_shipment_import_task.delay(batch.pk))
            messages.success(request, "Valid rows queued for shipment creation.")
        elif (
            action == "retry_failed"
            and batch.status in {"completed_with_errors", "failed"}
            and batch.rows.filter(status="failed").exists()
        ):
            with transaction.atomic():
                batch.rows.filter(status="failed").update(status="pending", error_message="")
                batch.status = "queued"
                batch.save(update_fields=["status", "updated_at"])
                from .tasks import process_shipment_import_task

                transaction.on_commit(lambda: process_shipment_import_task.delay(batch.pk))
            messages.success(request, "Failed rows queued for retry.")
        else:
            messages.error(request, "This import cannot perform that action in its current state.")
        return redirect("shipment_import_detail", pk=batch.pk)

    page_obj = Paginator(batch.rows.select_related("shipment"), 50).get_page(request.GET.get("page"))
    return render(
        request,
        "shipments/import_detail.html",
        {"batch": batch, "page_obj": page_obj},
    )


@login_required
def shipment_label_pdf(request, pk):
    """
    Renders standard 4x6-inch thermal shipping label PDF.
    """
    business = request.user.profile.get_or_create_business()
    shipment = get_object_or_404(Shipment, pk=pk, business=business)
    public_url = request.build_absolute_uri(reverse("public_tracking")) + f"?tracking_number={shipment.tracking_number}"
    
    pdf_bytes = generate_thermal_label_pdf(shipment, public_url)
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    disposition = "attachment" if request.GET.get("download") else "inline"
    response["Content-Disposition"] = f'{disposition}; filename="label-{shipment.tracking_number}.pdf"'
    return response


@login_required
def barcode_scanner_view(request):
    """
    Dispatch scanner console for continuous camera barcode/QR scanning.
    """
    business = request.user.profile.get_or_create_business()
    return render(
        request,
        "shipments/scanner.html",
        {
            "business": business,
            "status_choices": [
                ("in_transit", "In Transit"),
                ("out_for_delivery", "Out For Delivery"),
                ("picked_up", "Picked Up"),
            ],
        },
    )


@login_required
@require_POST
def batch_update_api(request):
    """
    Asynchronous batch dispatcher updating multiple scanned shipments simultaneously.
    Strictly scoped to user's business tenant.
    """
    business = request.user.profile.get_or_create_business()
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid_json", "message": "Malformed JSON payload."}, status=400)

    tracking_numbers = payload.get("tracking_numbers", [])
    target_status = payload.get("status")
    location = payload.get("location", "").strip()
    note = payload.get("note", "").strip()

    if not tracking_numbers:
        return JsonResponse({"error": "empty_batch", "message": "No tracking numbers provided."}, status=400)

    if target_status not in dict(STATUS_CHOICES):
        return JsonResponse({"error": "invalid_status", "message": f"Invalid status: {target_status}"}, status=400)

    updated = []
    failed = []

    # Filter strictly by business tenant
    shipments = Shipment.objects.filter(business=business, tracking_number__in=tracking_numbers)
    found_numbers = {s.tracking_number for s in shipments}

    for num in tracking_numbers:
        if num not in found_numbers:
            failed.append({"tracking_number": num, "reason": "Shipment not found in tenant fleet."})

    for shipment in shipments:
        if not shipment.can_transition(shipment.status, target_status):
            failed.append({
                "tracking_number": shipment.tracking_number,
                "reason": f"Cannot transition from '{shipment.status}' to '{target_status}'.",
            })
            continue

        try:
            with transaction.atomic():
                shipment.transition_to(
                    target_status,
                    location=location,
                    note=note or f"Batch dispatched via scanner console.",
                )
            updated.append(shipment.tracking_number)
        except Exception as exc:
            failed.append({"tracking_number": shipment.tracking_number, "reason": str(exc)})

    return JsonResponse({
        "success": True,
        "target_status": target_status,
        "updated_count": len(updated),
        "updated": updated,
        "failed_count": len(failed),
        "failed": failed,
    })


@login_required
def profile_view(request):
    profile = request.user.profile
    business = profile.get_or_create_business()
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
                "business": business,
                "webhook_logs": business.webhook_logs.all()[:15],
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

            # Update business and profile
            business.webhook_url = endpoint
            business.webhook_events = events
            business.save(update_fields=["webhook_url", "webhook_events"])

            profile.webhook_url = endpoint
            profile.webhook_events = events
            profile.save(update_fields=["webhook_url", "webhook_events"])

            messages.success(request, "Webhook configuration updated. Deliveries are actively queued via Celery.")
            return redirect(f"{reverse('profile')}?tab=api")

        settings_form = ProfileSettingsForm(request.POST, instance=profile)
        if settings_form.is_valid():
            profile = settings_form.save()
            messages.success(request, "Organization settings updated successfully.")
            return redirect(f"{reverse('profile')}?tab={active_tab}")
        password_form = PasswordChangeForm(request.user)
    else:
        settings_form = ProfileSettingsForm(instance=profile)
        password_form = PasswordChangeForm(request.user)

    api_form = ProfileSettingsForm(instance=profile)
    webhook_logs = business.webhook_logs.all()[:15]

    return render(request, "profile.html", {
        "active_tab": active_tab,
        "settings_form": settings_form,
        "password_form": password_form,
        "api_form": api_form,
        "business": business,
        "organization_id": f"biz_{business.pk:04d}",
        "webhook_logs": webhook_logs,
    })


@ratelimit(key="ip", rate="60/m", block=False)
def public_tracking_page(request):
    was_limited = getattr(request, "limited", False)
    if was_limited:
        return render(
            request,
            "public_tracking.html",
            {
                "rate_limited": True,
                "tracking_number": "",
                "shipment": None,
                "recent_shipments": [],
                "shipment_status_choices": STATUS_CHOICES,
            },
            status=429,
        )

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
            "rate_limited": False,
        },
    )


@ratelimit(key="ip", rate="30/m", block=False)
def public_tracking_api(request, tracking_number):
    was_limited = getattr(request, "limited", False)
    if was_limited:
        response = JsonResponse(
            {
                "error": "rate_limit_exceeded",
                "message": "Too many tracking requests. Please wait before retrying.",
                "retry_after_seconds": 60,
            },
            status=429,
        )
        response["Retry-After"] = "60"
        response["Cache-Control"] = "no-store, max-age=0"
        return response

    shipment = get_object_or_404(Shipment, tracking_number=tracking_number)
    data = {
        "tracking_number": shipment.tracking_number,
        "status": shipment.status,
        "carrier": shipment.carrier,
        "origin": shipment.origin,
        "destination": shipment.destination,
        "updated_at": shipment.updated_at.isoformat(),
        "history": [
            {
                "status": entry.status,
                "location": entry.location,
                "note": entry.note,
                "created_at": entry.created_at.isoformat(),
                "failure_reason": entry.failure_reason or None,
            }
            for entry in shipment.history.all()
        ],
    }
    response = JsonResponse(data)
    response["Cache-Control"] = "public, max-age=15"
    return response
