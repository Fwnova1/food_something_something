from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0007_qualityinspection"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="is_surplus",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="product",
            name="surplus_discount_percent",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="product",
            name="surplus_message",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="product",
            name="surplus_expires_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="product",
            name="surplus_notified_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
