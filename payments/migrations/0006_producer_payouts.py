from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0007_remove_order_chat_models"),
        ("payments", "0005_refundrequest_processing_started_at"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ProducerPayout",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("week_start", models.DateField(db_index=True)),
                ("week_end", models.DateField(db_index=True)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=12)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("paid", "Paid")], db_index=True, default="paid", max_length=20)),
                ("paid_at", models.DateTimeField(blank=True, null=True)),
                ("note", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("producer", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="producer_payouts", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-week_end", "-created_at"]},
        ),
        migrations.CreateModel(
            name="ProducerPayoutItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("producer_amount", models.DecimalField(decimal_places=2, max_digits=10)),
                ("order_item", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="payout_item", to="orders.orderitem")),
                ("payout", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="items", to="payments.producerpayout")),
            ],
            options={"ordering": ["id"]},
        ),
    ]
