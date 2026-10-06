from tempfile import TemporaryDirectory
from datetime import timedelta
import hashlib
import secrets
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import DeliveryPreferenceRequest, Shipment, ShipmentImportBatch


class ShipmentWorkflowTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="tester",
            email="tester@logitrack.test",
            password="secure-pass-123",
        )

    @override_settings(
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
        }
    )
    def test_landing_navigation_targets_sections_and_dispatch_route(self):
        response = self.client.get(reverse("landing"))

        self.assertEqual(response.status_code, 200)
        for section_id in ("telemetry", "fleet-api", "docs", "enterprise"):
            self.assertContains(response, f'id="{section_id}"')
            self.assertContains(response, f'href="#{section_id}"')
        self.assertContains(response, 'class="h-full scroll-smooth"')
        self.assertContains(response, reverse("shipment_create"))
        self.assertContains(response, "Generate API key")
        self.assertContains(response, "04 / Enterprise architecture")
        self.assertContains(response, "Mission-critical reliability for enterprise fleets.")
        self.assertContains(response, "Dedicated Ingestion Clusters")
        self.assertContains(response, "Compliance &amp; SOC 2")
        self.assertContains(response, "Custom WMS / ERP Connectors")
        self.assertContains(response, "Schedule Architecture Review")
        self.assertContains(response, "05 / Operations")
        self.assertContains(response, "Launch Dispatch Console")
        self.assertContains(response, "View Live Demo")
        self.assertContains(response, "hidden items-center gap-2 rounded-lg bg-emerald-400")

    def test_valid_transition_sequence(self):
        shipment = Shipment.objects.create(
            user=self.user,
            tracking_number="ABCD1234EF",
            recipient_name="Ava Smith",
            recipient_phone="+1 555 123 4567",
            origin="Seattle, WA",
            destination="Denver, CO",
            description="Sample parcel",
            status="pending",
        )

        shipment.transition_to("picked_up", location="Seattle Hub", note="Collection complete")
        shipment.transition_to("in_transit", location="Denver Line", note="Package moving")
        self.assertEqual(shipment.status, "in_transit")
        self.assertEqual(shipment.history.count(), 2)

    def test_invalid_transition_is_rejected(self):
        shipment = Shipment.objects.create(
            user=self.user,
            tracking_number="ZZZZ1234XY",
            recipient_name="Ava Smith",
            recipient_phone="+1 555 123 4567",
            origin="Seattle, WA",
            destination="Denver, CO",
            description="Sample parcel",
            status="pending",
        )

        with self.assertRaises(Exception):
            shipment.transition_to("delivered", location="Final stop", note="Not allowed yet")

    def test_terminal_status_cannot_transition(self):
        shipment = Shipment.objects.create(
            user=self.user,
            tracking_number="QWER9876MN",
            recipient_name="Noah Lee",
            recipient_phone="+1 555 987 6543",
            origin="Chicago, IL",
            destination="Boston, MA",
            description="Late delivery",
            status="delivered",
        )

        with self.assertRaises(Exception):
            shipment.transition_to("failed", location="Warehouse", note="Attempted invalid update")

    @override_settings(
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
        }
    )
    def test_public_tracking_search_adds_private_recent_lookup(self):
        shipment = Shipment.objects.create(
            user=self.user,
            tracking_number="LT-94021",
            recipient_name="Jordan Blake",
            recipient_phone="+1 555 010 2040",
            origin="Austin, TX",
            destination="Denver, CO",
            status="in_transit",
        )

        response = self.client.get(
            reverse("public_tracking"),
            {"tracking_number": shipment.tracking_number.lower()},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["shipment"], shipment)
        self.assertEqual(response.context["recent_shipments"], [shipment])
        self.assertEqual(
            self.client.session["recent_tracking_numbers"],
            [shipment.tracking_number],
        )

        other_browser = self.client_class()
        other_response = other_browser.get(reverse("public_tracking"))
        self.assertEqual(other_response.context["recent_shipments"], [])

    @override_settings(
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
        }
    )
    def test_unknown_tracking_number_shows_not_found_state(self):
        response = self.client.get(
            reverse("public_tracking"),
            {"tracking_number": "UNKNOWN-123"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["shipment"])
        self.assertContains(response, "No shipment found.")

    @override_settings(
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
        }
    )
    def test_signup_creates_email_username_and_profile_without_confirmation_field(self):
        response = self.client.post(
            reverse("signup"),
            {
                "business_name": "Northstar Freight",
                "email": "OPS@northstar.example",
                "password": "FleetSecure9!",
            },
        )

        self.assertRedirects(response, reverse("dashboard"))
        user = get_user_model().objects.get(email="ops@northstar.example")
        self.assertEqual(user.username, "ops@northstar.example")
        self.assertEqual(user.profile.business_name, "Northstar Freight")
        self.assertTrue(user.check_password("FleetSecure9!"))

    @override_settings(
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
        }
    )
    def test_email_login_remembers_device_for_thirty_days(self):
        response = self.client.post(
            reverse("login"),
            {
                "username": self.user.email,
                "password": "secure-pass-123",
                "remember_device": "on",
            },
        )

        self.assertRedirects(response, reverse("dashboard"))
        self.assertEqual(self.client.session.get_expiry_age(), 60 * 60 * 24 * 30)

    @override_settings(
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
        }
    )
    def test_password_reset_form_is_routed(self):
        response = self.client.get(reverse("password_reset"))

        self.assertEqual(response.status_code, 200)

    @override_settings(
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
        }
    )
    def test_operations_pages_render_for_authenticated_user(self):
        self.client.force_login(self.user)

        for url in (
            reverse("dashboard"),
            reverse("shipments_list"),
            reverse("profile"),
            reverse("profile") + "?tab=security",
            reverse("profile") + "?tab=api",
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    @override_settings(
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
        }
    )
    def test_demo_telemetry_populates_only_current_users_fleet(self):
        other_user = get_user_model().objects.create_user(username="other")
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("populate_demo_telemetry"),
            {"next": reverse("dashboard")},
        )

        self.assertRedirects(response, reverse("dashboard"))
        self.assertEqual(Shipment.objects.filter(user=self.user).count(), 6)
        self.assertEqual(Shipment.objects.filter(user=other_user).count(), 0)
        self.assertEqual(Shipment.objects.filter(user=self.user, carrier="FedEx").count(), 2)

    def test_manifest_export_is_scoped_to_current_user(self):
        Shipment.objects.create(
            user=self.user,
            tracking_number="EXPT123456",
            recipient_name="Export Recipient",
            recipient_phone="555",
            origin="SFO",
            destination="ORD",
            carrier="FedEx",
            status="in_transit",
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse("shipments_list"), {"export": "json"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="logitrack-manifest.json"')
        self.assertEqual(response.json()[0]["carrier"], "FedEx")

    @override_settings(
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
        }
    )
    def test_shipment_creation_console_renders_and_saves_supported_fields(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("shipment_create"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Create New Consignment")
        self.assertContains(response, "Consignment Preview")

        response = self.client.post(
            reverse("shipment_create"),
            {
                "recipient_name": "Morgan Reed",
                "recipient_phone": "+1 555 010 2030",
                "recipient_email": "morgan@example.test",
                "origin": "Chicago Hub",
                "destination": "Denver, CO",
                "carrier": "FedEx Express",
                "description": "Leave at receiving dock",
            },
        )

        self.assertEqual(response.status_code, 302)
        shipment = Shipment.objects.get(user=self.user, recipient_name="Morgan Reed")
        self.assertEqual(shipment.carrier, "FedEx Express")
        self.assertEqual(shipment.origin, "Chicago Hub")
        self.assertEqual(shipment.description, "Leave at receiving dock")
        self.assertEqual(shipment.recipient_email, "morgan@example.test")

    @override_settings(
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
        }
    )
    def test_general_settings_and_webhook_preferences_persist(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("profile"),
            {
                "tab": "general",
                "business_name": "Northstar Logistics",
                "timezone": "America/Chicago",
                "distance_unit": "kilometers",
                "currency": "EUR",
            },
        )
        self.assertRedirects(response, reverse("profile") + "?tab=general")
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.business_name, "Northstar Logistics")
        self.assertEqual(self.user.profile.distance_unit, "kilometers")
        self.assertEqual(self.user.profile.currency, "EUR")

        response = self.client.post(
            reverse("profile"),
            {
                "tab": "api",
                "webhook_url": "https://hooks.example.test/logitrack",
                "webhook_events": ["shipment.created", "shipment.delivered"],
            },
        )
        self.assertRedirects(response, reverse("profile") + "?tab=api")
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.webhook_url, "https://hooks.example.test/logitrack")
        self.assertEqual(self.user.profile.webhook_events, ["shipment.created", "shipment.delivered"])

    @override_settings(
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
        }
    )
    def test_webhook_rejects_non_https_urls(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("profile"),
            {"tab": "api", "webhook_url": "http://hooks.example.test/"},
        )

        self.assertRedirects(response, reverse("profile") + "?tab=api")
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.webhook_url, "")


class EnterpriseSupplyChainTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user_a = User.objects.create_user(
            username="tenant_a",
            email="tenant_a@fleet.test",
            password="secure-pass-123",
        )
        self.user_b = User.objects.create_user(
            username="tenant_b",
            email="tenant_b@fleet.test",
            password="secure-pass-123",
        )
        self.shipment_a = Shipment.objects.create(
            user=self.user_a,
            recipient_name="Atlas Corp",
            recipient_phone="+1 555 111 2222",
            origin="Seattle, WA",
            destination="Portland, OR",
            status="pending",
        )

    def test_multi_tenant_isolation(self):
        """Strict multi-tenant scoping ensures Tenant B cannot access Tenant A shipments."""
        self.client.force_login(self.user_b)
        
        # Detail view must return 404
        response = self.client.get(reverse("shipment_detail", args=[self.shipment_a.pk]))
        self.assertEqual(response.status_code, 404)

        # Shipments list for tenant B must not contain shipment A
        response = self.client.get(reverse("shipments_list"))
        self.assertNotContains(response, self.shipment_a.tracking_number)

    def test_delivery_pin_generation_and_verification(self):
        """Ensures 4-digit PIN is generated, hashed, and required for delivery."""
        self.assertTrue(self.shipment_a.delivery_pin)
        self.assertTrue(self.shipment_a.delivery_pin_raw)
        self.assertEqual(len(self.shipment_a.delivery_pin_raw), 4)

        # Transition to picked_up -> in_transit -> out_for_delivery
        self.shipment_a.transition_to("picked_up")
        self.shipment_a.transition_to("in_transit")
        self.shipment_a.transition_to("out_for_delivery")

        # Wrong PIN must fail
        with self.assertRaises(Exception):
            self.shipment_a.transition_to("delivered", delivery_pin="0000")

        # Correct PIN succeeds
        self.shipment_a.transition_to(
            "delivered",
            delivery_pin=self.shipment_a.delivery_pin_raw,
            delivery_lat=47.6062,
            delivery_lng=-122.3321,
        )
        self.assertEqual(self.shipment_a.status, "delivered")
        self.assertEqual(float(self.shipment_a.delivery_lat), 47.6062)

    def test_out_for_delivery_queues_one_hashed_token_invitation_after_commit(self):
        self.shipment_a.recipient_email = "recipient@example.test"
        self.shipment_a.save(update_fields=["recipient_email"])

        with patch("shipments.tasks.queue_delivery_preference_invitation") as queue_invitation:
            with self.captureOnCommitCallbacks(execute=True):
                self.shipment_a.transition_to("picked_up")
                self.shipment_a.transition_to("in_transit")
                self.shipment_a.transition_to("out_for_delivery")

        request = DeliveryPreferenceRequest.objects.get(shipment=self.shipment_a)
        queue_invitation.assert_called_once()
        request_id, raw_token = queue_invitation.call_args.args
        self.assertEqual(request_id, request.pk)
        self.assertTrue(request.matches_token(raw_token))
        self.assertNotEqual(request.token_digest, raw_token)
        self.assertLessEqual(request.expires_at, timezone.now() + timedelta(days=7))

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        PUBLIC_BASE_URL="https://logitrack.example.test",
    )
    def test_preference_invitation_email_is_asynchronous_and_idempotent(self):
        self.shipment_a.recipient_email = "recipient@example.test"
        self.shipment_a.save(update_fields=["recipient_email"])
        token = secrets.token_urlsafe(32)
        request = DeliveryPreferenceRequest.objects.create(
            shipment=self.shipment_a,
            token_digest=hashlib.sha256(token.encode("utf-8")).hexdigest(),
            expires_at=timezone.now() + timedelta(days=7),
        )

        from shipments.tasks import send_delivery_preference_invitation

        result = send_delivery_preference_invitation.apply(args=[request.pk, token])
        self.assertTrue(result.successful())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.shipment_a.recipient_email])
        self.assertIn("https://logitrack.example.test/delivery-preferences/", mail.outbox[0].body)
        self.assertIn(token, mail.outbox[0].body)

        request.refresh_from_db()
        self.assertIsNotNone(request.sent_at)
        send_delivery_preference_invitation.apply(args=[request.pk, token])
        self.assertEqual(len(mail.outbox), 1)

    def test_recipient_preference_link_validates_token_expiry_and_single_submission(self):
        token = secrets.token_urlsafe(32)
        request = DeliveryPreferenceRequest.objects.create(
            shipment=self.shipment_a,
            token_digest=hashlib.sha256(token.encode("utf-8")).hexdigest(),
            expires_at=timezone.now() + timedelta(days=7),
        )
        url = reverse(
            "delivery_preferences",
            kwargs={"public_id": request.public_id, "token": token},
        )

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store, max-age=0")
        self.assertEqual(self.client.get(reverse(
            "delivery_preferences",
            kwargs={"public_id": request.public_id, "token": token + "bad"},
        )).status_code, 404)

        requested_date = timezone.localdate() + timedelta(days=2)
        response = self.client.post(
            url,
            {
                "delivery_instructions": "Leave at the side entrance.",
                "requested_delivery_date": requested_date.isoformat(),
            },
        )
        self.assertEqual(response.status_code, 200)
        request.refresh_from_db()
        self.assertEqual(request.delivery_instructions, "Leave at the side entrance.")
        self.assertEqual(request.requested_delivery_date, requested_date)
        self.assertIsNotNone(request.submitted_at)
        self.shipment_a.refresh_from_db()
        self.assertIsNone(self.shipment_a.estimated_delivery)

        self.client.post(url, {"delivery_instructions": "Replace my first request."})
        request.refresh_from_db()
        self.assertEqual(request.delivery_instructions, "Leave at the side entrance.")

        request.expires_at = timezone.now() - timedelta(seconds=1)
        request.save(update_fields=["expires_at"])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_failure_reason_tracking(self):
        """Failed transition requires an exception reason."""
        self.shipment_a.transition_to("failed", failure_reason="gate_locked")
        self.assertEqual(self.shipment_a.status, "failed")
        self.assertEqual(self.shipment_a.failure_reason, "gate_locked")

    def test_4x6_thermal_label_pdf_rendering(self):
        """Tests that the 4x6 shipping label PDF generates valid PDF binary."""
        self.client.force_login(self.user_a)
        response = self.client.get(reverse("shipment_label_pdf", args=[self.shipment_a.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF-"))

    def test_batch_update_dispatcher_api(self):
        """Tests bulk barcode dispatch endpoint updating multiple items atomically."""
        self.client.force_login(self.user_a)
        shipment_a2 = Shipment.objects.create(
            user=self.user_a,
            recipient_name="Beacon Labs",
            recipient_phone="+1 555 333 4444",
            origin="Seattle, WA",
            destination="Spokane, WA",
            status="pending",
        )

        import json
        payload = {
            "tracking_numbers": [self.shipment_a.tracking_number, shipment_a2.tracking_number],
            "status": "picked_up",
            "location": "North Terminal",
            "note": "Batch intake",
        }
        response = self.client.post(
            reverse("batch_update_api"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["updated_count"], 2)

        self.shipment_a.refresh_from_db()
        self.assertEqual(self.shipment_a.status, "picked_up")

    def test_webhook_hmac_signing(self):
        """Verifies HMAC-SHA256 signature calculation matches specification."""
        from shipments.services.webhooks import build_webhook_headers, sign_payload
        secret = "test-secret-key-12345"
        payload_bytes = b'{"event":"shipment.delivered"}'
        sig = sign_payload(secret, payload_bytes)
        headers = build_webhook_headers(secret, payload_bytes, "shipment.delivered")
        self.assertEqual(headers["X-LogiTrack-Signature"], f"sha256={sig}")
        self.assertEqual(headers["X-LogiTrack-Event"], "shipment.delivered")

    def test_public_tracking_api_omits_sensitive_delivery_proof(self):
        """Public tracking must not expose POD files, coordinates, or PIN data."""
        self.shipment_a.delivery_lat = "47.606200"
        self.shipment_a.delivery_lng = "-122.332100"
        self.shipment_a.recipient_signature = "pod/signatures/private.png"
        self.shipment_a.delivery_photo = "pod/photos/private.jpg"
        self.shipment_a.save(
            update_fields=["delivery_lat", "delivery_lng", "recipient_signature", "delivery_photo"]
        )

        response = self.client.get(reverse("public_tracking_api", args=[self.shipment_a.tracking_number]))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["tracking_number"], self.shipment_a.tracking_number)
        self.assertNotIn("proof_of_delivery", data)
        self.assertNotIn("47.6062", response.content.decode())
        self.assertNotIn("-122.3321", response.content.decode())
        self.assertNotIn("private.png", response.content.decode())

    def test_webhook_task_success_log(self):
        """Tests successful webhook dispatch logs to WebhookDeliveryLog."""
        from unittest.mock import patch
        from shipments.tasks import dispatch_webhook_task
        from shipments.models import WebhookDeliveryLog

        business = self.shipment_a.business
        business.webhook_url = "https://fleet.test/webhook"
        business.webhook_events = ["shipment.delivered"]
        business.save()

        with patch("shipments.tasks.deliver_webhook_sync") as mock_deliver:
            mock_deliver.return_value = (200, '{"ok": true}')
            res = dispatch_webhook_task.apply(
                args=[business.id, "shipment.delivered", {"test": "payload"}, self.shipment_a.id]
            )
            self.assertTrue(res.successful())
            log = WebhookDeliveryLog.objects.filter(business=business, event_type="shipment.delivered").first()
            self.assertIsNotNone(log)
            self.assertEqual(log.status, "success")
            self.assertEqual(log.status_code, 200)

    def test_webhook_dead_letter_logging(self):
        """Tests that exhausted retries log directly to the Dead Letter table."""
        from unittest.mock import patch
        import requests
        from shipments.tasks import dispatch_webhook_task
        from shipments.models import WebhookDeliveryLog

        business = self.shipment_a.business
        business.webhook_url = "https://unreachable.fleet.test/webhook"
        business.webhook_events = ["shipment.exception"]
        business.save()

        with patch("shipments.tasks.deliver_webhook_sync") as mock_deliver:
            mock_deliver.side_effect = requests.RequestException("Host unreachable")
            # Run task at max retry level
            res = dispatch_webhook_task.apply(
                args=[business.id, "shipment.exception", {"test": "payload"}, self.shipment_a.id],
                retries=3,
            )
            log = WebhookDeliveryLog.objects.filter(business=business, event_type="shipment.exception").first()
            self.assertIsNotNone(log)
            self.assertEqual(log.status, "dead_letter")
            self.assertIn("Host unreachable", log.error_message)

    def test_rate_limiting_429_response_format(self):
        """Tests that rate limit violation on tracking API returns 429 with expected JSON structure."""
        from unittest.mock import patch
        from django.test import RequestFactory
        from shipments.views import public_tracking_api

        factory = RequestFactory()
        req = factory.get(reverse("public_tracking_api", args=[self.shipment_a.tracking_number]))
        req.limited = True

        resp = public_tracking_api(req, self.shipment_a.tracking_number)
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(resp["Retry-After"], "60")
        import json
        body = json.loads(resp.content)
        self.assertEqual(body["error"], "rate_limit_exceeded")


class ShipmentImportTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="importer",
            email="importer@logitrack.test",
            password="secure-pass-123",
        )
        self.business = self.user.profile.get_or_create_business()

    def make_batch(self, content):
        return ShipmentImportBatch.objects.create(
            business=self.business,
            user=self.user,
            source_file=SimpleUploadedFile("manifest.csv", content.encode("utf-8"), content_type="text/csv"),
        )

    def test_upload_queues_background_validation_and_template_has_expected_headers(self):
        self.client.force_login(self.user)
        with patch("shipments.tasks.validate_shipment_import_task.delay") as queue_task:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(
                    reverse("shipment_import_create"),
                    {"csv_file": SimpleUploadedFile("manifest.csv", b"recipient_name,recipient_phone,origin,destination\n")},
                )

        self.assertRedirects(response, reverse("shipment_import_detail", args=[1]))
        batch = ShipmentImportBatch.objects.get(business=self.business)
        queue_task.assert_called_once_with(batch.pk)

        detail_response = self.client.get(reverse("shipment_import_detail", args=[batch.pk]))
        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, "Manifest review")
        self.assertNotContains(detail_response, "Retry failed rows")

        upload_response = self.client.get(reverse("shipment_import_create"))
        self.assertEqual(upload_response.status_code, 200)
        self.assertContains(upload_response, "Download template")

        template_response = self.client.get(reverse("shipment_import_template"))
        self.assertEqual(template_response.status_code, 200)
        self.assertIn(b"customer_reference,recipient_name,recipient_phone,recipient_email,origin,destination", template_response.content)

    def test_validation_reports_bad_rows_and_import_is_idempotent(self):
        content = (
            "customer_reference,recipient_name,recipient_phone,recipient_email,origin,destination,carrier,estimated_delivery,description\n"
            "EXT-001,Jordan Lee,555-0100,jordan@example.test,Seattle,Denver,Northstar,2026-10-08 14:30,Fragile\n"
            "EXT-001,Casey Rae,555-0101,casey@example.test,Seattle,Boise,Northstar,,Duplicate reference\n"
            "EXT-003,Alex Kim,555-0102,alex@example.test,Seattle,,Northstar,,Missing destination\n"
        )
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            batch = self.make_batch(content)
            from .services.shipment_imports import process_shipment_import, validate_shipment_import

            self.assertEqual(validate_shipment_import(batch.pk), "ready")
            batch.refresh_from_db()
            self.assertEqual(batch.total_rows, 3)
            self.assertEqual(batch.valid_rows, 1)
            self.assertEqual(batch.failed_rows, 2)
            self.assertFalse(batch.source_file)
            self.assertEqual(batch.rows.filter(status="invalid").count(), 2)

            batch.status = "queued"
            batch.save(update_fields=["status"])
            self.assertEqual(process_shipment_import(batch.pk), "completed_with_errors")
            batch.refresh_from_db()
            self.assertEqual(batch.imported_rows, 1)
            self.assertEqual(batch.rows.get(row_number=2).shipment.customer_reference, "EXT-001")
            self.assertEqual(batch.rows.get(row_number=2).shipment.recipient_email, "jordan@example.test")

            self.assertEqual(process_shipment_import(batch.pk), "completed_with_errors")
            self.assertEqual(Shipment.objects.filter(business=self.business, customer_reference="EXT-001").count(), 1)

    def test_import_detail_is_scoped_to_the_current_business(self):
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            batch = self.make_batch("recipient_name,recipient_phone,origin,destination\n")
            other_user = get_user_model().objects.create_user(username="other-importer")
            self.client.force_login(other_user)

            response = self.client.get(reverse("shipment_import_detail", args=[batch.pk]))

            self.assertEqual(response.status_code, 404)


