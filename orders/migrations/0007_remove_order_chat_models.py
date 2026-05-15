from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0006_order_conversation_messages"),
    ]

    operations = [
        migrations.DeleteModel(
            name="OrderMessage",
        ),
        migrations.DeleteModel(
            name="OrderConversation",
        ),
    ]
