from django.db import migrations
from django.db.models import Avg, Count


def refresh_review_ratings(apps, schema_editor):
    Product = apps.get_model("store", "Product")
    Review = apps.get_model("store", "Review")
    database = schema_editor.connection.alias
    for product in Product.objects.using(database).all().only("pk", "manual_rating", "manual_reviews"):
        summary = Review.objects.using(database).filter(
            product_id=product.pk, approved=True,
        ).aggregate(average=Avg("rating"), count=Count("id"))
        if summary["count"]:
            Product.objects.using(database).filter(pk=product.pk).update(
                rating=summary["average"], reviews=summary["count"],
            )
        else:
            Product.objects.using(database).filter(pk=product.pk).update(
                rating=product.manual_rating, reviews=product.manual_reviews,
            )


class Migration(migrations.Migration):

    dependencies = [
        ("store", "0025_publish_existing_reviews"),
    ]

    operations = [
        migrations.RunPython(refresh_review_ratings, migrations.RunPython.noop),
    ]
