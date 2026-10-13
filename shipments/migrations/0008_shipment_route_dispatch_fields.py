from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("shipments", "0007_business_carrier_integration_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="shipment",
            name="dispatch_priority",
            field=models.CharField(choices=[("standard", "Standard"), ("priority", "Priority"), ("rush", "Rush")], default="standard", max_length=18),
        ),
        migrations.AddField(
            model_name="shipment",
            name="dispatch_window_end",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="shipment",
            name="dispatch_window_start",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="shipment",
            name="driver_name",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="shipment",
            name="route_code",
            field=models.CharField(blank=True, default="", max_length=32),
        ),
        migrations.AddField(
            model_name="shipment",
            name="sla_due_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
