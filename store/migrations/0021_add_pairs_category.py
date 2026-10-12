from django.db import migrations


def add_pairs_category(apps, schema_editor):
    Category = apps.get_model("store", "Category")
    Category.objects.using(schema_editor.connection.alias).get_or_create(
        name="Pairs",
        defaults={
            "slug": "pairs",
            "tagline": "Paired shirts and trousers.",
            "show_on_home": False,
            "order": 3,
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ("store", "0020_product_custom_print_dimensions"),
    ]

    operations = [
        migrations.RunPython(add_pairs_category, migrations.RunPython.noop),
    ]
