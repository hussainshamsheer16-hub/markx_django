from django.db import migrations


def publish_existing_reviews(apps, schema_editor):
    Review = apps.get_model("store", "Review")
    Review.objects.using(schema_editor.connection.alias).filter(approved=False).update(approved=True)


class Migration(migrations.Migration):

    dependencies = [
        ("store", "0024_hide_other_categories"),
    ]

    operations = [
        migrations.RunPython(publish_existing_reviews, migrations.RunPython.noop),
    ]
