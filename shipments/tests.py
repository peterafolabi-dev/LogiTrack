from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Shipment


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

    def test_public_tracking_api_payload(self):
        """Tests public tracking API response format and proof of delivery inclusion."""
        response = self.client.get(reverse("public_tracking_api", args=[self.shipment_a.tracking_number]))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["tracking_number"], self.shipment_a.tracking_number)
        self.assertIn("proof_of_delivery", data)

