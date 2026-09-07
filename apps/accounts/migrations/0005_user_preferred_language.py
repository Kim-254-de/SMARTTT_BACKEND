from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0004_adapt_passwordresettoken"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="preferred_language",
            field=models.CharField(
                choices=[("en", "English"), ("sw", "Swahili"), ("fr", "French")],
                default="en",
                max_length=5,
            ),
        ),
    ]
