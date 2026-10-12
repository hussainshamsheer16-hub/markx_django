from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("store", "0019_custom_request_status_owner_and_text_color"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="custom_width_cm",
            field=models.DecimalField(
                decimal_places=1,
                default=20.0,
                max_digits=5,
                verbose_name="Custom print width (cm)",
            ),
        ),
        migrations.AddField(
            model_name="product",
            name="custom_height_cm",
            field=models.DecimalField(
                decimal_places=1,
                default=28.0,
                max_digits=5,
                verbose_name="Custom print height (cm)",
            ),
        ),
    ]
