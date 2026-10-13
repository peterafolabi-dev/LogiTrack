from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("shipments", "0006_business_delivery_reminder_hours_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="business",
            name="carrier_account_number",
            field=models.CharField(blank=True, default="", max_length=80),
        ),
        migrations.AddField(
            model_name="business",
            name="carrier_api_key",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="business",
            name="carrier_provider",
            field=models.CharField(
                choices=[("manual", "Manual / In-house"), ("fedex", "FedEx"), ("ups", "UPS"), ("dhl", "DHL")],
                default="manual",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="business",
            name="carrier_sync_enabled",
            field=models.BooleanField(default=False),
        ),
    ]
