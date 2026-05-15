from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0002_refunds_and_events"),
    ]

    operations = [
        migrations.CreateModel(
            name="StripeWebhookReceipt",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_id", models.CharField(db_index=True, max_length=255, unique=True)),
                ("event_type", models.CharField(db_index=True, max_length=128)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("received", "Received"),
                            ("processed", "Processed"),
                            ("failed", "Failed"),
                            ("ignored", "Ignored"),
                        ],
                        db_index=True,
                        default="received",
                        max_length=20,
                    ),
                ),
                ("error_message", models.TextField(blank=True)),
                ("received_at", models.DateTimeField(auto_now_add=True)),
                ("processed_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "ordering": ["-received_at"],
            },
        ),
    ]

