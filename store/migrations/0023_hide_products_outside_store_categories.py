from django.db import migrations


def hide_non_store_products(apps, schema_editor):
    Product = apps.get_model("store", "Product")
    Product.objects.using(schema_editor.connection.alias).filter(active=True).exclude(
        category__name__in=("Shirts", "Trousers", "Pairs")
    ).update(active=False)


class Migration(migrations.Migration):

    dependencies = [
        ("store", "0022_remove_product_custom_print_dimensions"),
    ]

    operations = [
        migrations.RunPython(hide_non_store_products, migrations.RunPython.noop),
    ]
