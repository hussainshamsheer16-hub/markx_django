from django.db import migrations, models


def rename_pair_catalog(apps, schema_editor):
    Category = apps.get_model("store", "Category")
    Product = apps.get_model("store", "Product")
    db = schema_editor.connection.alias

    old_category = Category.objects.using(db).filter(name__iexact="Tracksuits").first()
    pairs_category = Category.objects.using(db).filter(name__iexact="Pairs").first()
    if old_category and pairs_category:
        Product.objects.using(db).filter(category_id=old_category.pk).update(category_id=pairs_category.pk)
        old_category.delete(using=db)
    elif old_category:
        old_category.name = "Pairs"
        old_category.save(using=db, update_fields=["name"])

    for product in Product.objects.using(db).filter(name__icontains="tracksuit").iterator():
        product.name = product.name.replace("Tracksuit", "Pair").replace("tracksuit", "pair").replace("TRACKSUIT", "PAIR")
        product.save(using=db, update_fields=["name"])


class Migration(migrations.Migration):

    dependencies = [
        ("store", "0027_custom_request_resolved_postponed_statuses"),
    ]

    operations = [
        migrations.RunPython(rename_pair_catalog, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="product",
            name="product_type",
            field=models.CharField(default="shirt", help_text="shirt / trousers / pairs", max_length=30),
        ),
        migrations.AlterField(
            model_name="product",
            name="size_guide",
            field=models.CharField(
                choices=[
                    ("shirt", "Shirt (collar, chest and sleeve length)"),
                    ("set", "Pair set (jacket and trousers)"),
                    ("top", "Top (chest and length)"),
                    ("bottom", "Bottom (waist and inseam)"),
                    ("none", "No size guide"),
                ],
                default="shirt",
                max_length=10,
            ),
        ),
        migrations.AlterField(
            model_name="product",
            name="sizes",
            field=models.CharField(
                default="S,M,L,XL,XXL",
                help_text="Comma-separated sizes. Trousers use waist sizes 28, 30, 32, 34, 36, 38; pairs use S, M, L, XL, XXL.",
                max_length=100,
            ),
        ),
    ]
