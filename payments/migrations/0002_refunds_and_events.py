import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="payment",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("processing", "Processing"),
                    ("succeeded", "Succeeded"),
                    ("failed", "Failed"),
                    ("refund_pending", "Refund pending"),
                    ("partially_refunded", "Partially refunded"),
                    ("refunded", "Refunded"),
                ],
                db_index=True,
                default="pending",
                max_length=20,
            ),
        ),
        migrations.CreateModel(
            name="RefundRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("reason", models.TextField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("approved", "Approved"),
                            ("rejected", "Rejected"),
                            ("completed", "Completed"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("admin_note", models.TextField(blank=True)),
                ("stripe_refund_id", models.CharField(blank=True, max_length=255, null=True, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("processed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "payment",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="refund_requests",
                        to="payments.payment",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="refund_requests",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="refundrequest",
            index=models.Index(fields=["payment", "status"], name="payments_re_payment__9ed7f2_idx"),
        ),
        migrations.AddIndex(
            model_name="refundrequest",
            index=models.Index(fields=["user", "status"], name="payments_re_user_st_8d0c26_idx"),
        ),
        migrations.CreateModel(
            name="PaymentEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_type", models.CharField(db_index=True, max_length=64)),
                ("message", models.TextField()),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "payment",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="events",
                        to="payments.payment",
                    ),
                ),
            ],
            options={
                "ordering": ["created_at", "id"],
            },
        ),
        migrations.AddIndex(
            model_name="paymentevent",
            index=models.Index(fields=["payment", "created_at"], name="payments_pa_payment__40db44_idx"),
        ),
    ]

