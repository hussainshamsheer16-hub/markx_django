from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("store", "0021_add_pairs_category"),
    ]

    operations = [
        migrations.RemoveField(model_name="product", name="custom_width_cm"),
        migrations.RemoveField(model_name="product", name="custom_height_cm"),
    ]
