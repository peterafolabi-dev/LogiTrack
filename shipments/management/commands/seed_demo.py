from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from shipments.models import Shipment, StatusUpdate


class Command(BaseCommand):
    help = "Seed demo user and sample shipments"

    def handle(self, *args, **options):
        User = get_user_model()
        user, created = User.objects.get_or_create(username="demo")
        user.set_password("demo12345")
        user.email = "demo@logitrack.local"
        user.save()

        if hasattr(user, "profile"):
            user.profile.business_name = "North Loop Courier"
            user.profile.save()
        else:
            from shipments.models import Profile
            Profile.objects.create(user=user, business_name="North Loop Courier")

        sample_shipments = [
            ("pending", "Aiden Rivers", "+1 415 444 2222", "Seattle, WA", "Denver, CO", "Kitchen appliance delivery"),
            ("picked_up", "Maya Hall", "+1 646 555 1111", "Brooklyn, NY", "Boston, MA", "Art print shipment"),
            ("in_transit", "Louis Chen", "+1 305 555 6789", "Miami, FL", "Orlando, FL", "Medical supplies"),
            ("out_for_delivery", "Sofia Patel", "+1 213 888 1010", "Los Angeles, CA", "San Diego, CA", "Retail display boards"),
            ("delivered", "Noah Kim", "+1 512 333 9001", "Austin, TX", "Dallas, TX", "Gift basket"),
            ("failed", "Emma Scott", "+1 720 224 4455", "Phoenix, AZ", "Las Vegas, NV", "Fragile parcel"),
        ]

        for status, recipient_name, recipient_phone, origin, destination, description in sample_shipments:
            if Shipment.objects.filter(user=user, recipient_name=recipient_name).exists():
                continue
            shipment = Shipment.objects.create(
                user=user,
                tracking_number=Shipment.generate_unique_tracking_number(),
                recipient_name=recipient_name,
                recipient_phone=recipient_phone,
                origin=origin,
                destination=destination,
                description=description,
                status=status,
            )
            StatusUpdate.objects.create(
                shipment=shipment,
                status=status,
                location=origin,
                note=f"{status.replace('_', ' ').title()} update",
            )

        tracking_samples = [
            ("LT-94021", "in_transit", "Jordan Blake", "Austin, TX", "Denver, CO"),
            ("LT-88319", "out_for_delivery", "Riley Morgan", "Boston, MA", "New York, NY"),
            ("LT-12094", "delivered", "Casey Taylor", "Chicago, IL", "Austin, TX"),
        ]
        for tracking_number, status, recipient_name, origin, destination in tracking_samples:
            shipment, created = Shipment.objects.get_or_create(
                tracking_number=tracking_number,
                defaults={
                    "user": user,
                    "recipient_name": recipient_name,
                    "recipient_phone": "+1 555 010 2040",
                    "origin": origin,
                    "destination": destination,
                    "description": "LogiTrack sample shipment",
                    "status": status,
                },
            )
            if created:
                StatusUpdate.objects.create(
                    shipment=shipment,
                    status=status,
                    location=destination if status == "delivered" else origin,
                    note=f"Sample shipment: {status.replace('_', ' ')}",
                )

        self.stdout.write(self.style.SUCCESS("Demo data seeded."))
