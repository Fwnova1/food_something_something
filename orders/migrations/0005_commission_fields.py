from decimal import Decimal, ROUND_HALF_UP

from django.db import migrations, models


def _backfill_commission(apps, schema_editor):
    OrderItem = apps.get_model("orders", "OrderItem")
    rate = Decimal("0.05")
    for item in OrderItem.objects.all().iterator():
        gross = (item.price or Decimal("0.00")) * Decimal(int(item.quantity or 0))
        commission = (gross * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        producer = (gross - commission).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        OrderItem.objects.filter(pk=item.pk).update(
            gross_amount=gross.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            commission_amount=commission,
            producer_amount=producer,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0004_recurring_orders"),
    ]

    operations = [
        migrations.AddField(
            model_name="orderitem",
            name="gross_amount",
            field=models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=10),
        ),
        migrations.AddField(
            model_name="orderitem",
            name="commission_amount",
            field=models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=10),
        ),
        migrations.AddField(
            model_name="orderitem",
            name="producer_amount",
            field=models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=10),
        ),
        migrations.RunPython(_backfill_commission, migrations.RunPython.noop),
    ]

