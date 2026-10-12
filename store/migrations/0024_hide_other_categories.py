from django.db import migrations


def hide_other_categories(apps, schema_editor):
    Category = apps.get_model("store", "Category")
    Category.objects.using(schema_editor.connection.alias).exclude(
        name__in=("Shirts", "Trousers", "Pairs")
    ).update(show_on_home=False)


class Migration(migrations.Migration):

    dependencies = [
        ("store", "0023_hide_products_outside_store_categories"),
    ]

    operations = [
        migrations.RunPython(hide_other_categories, migrations.RunPython.noop),
    ]
