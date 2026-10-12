from django.db import migrations, models


def update_custom_request_statuses(apps, schema_editor):
    CustomRequest = apps.get_model("store", "CustomRequest")
    database = schema_editor.connection.alias
    CustomRequest.objects.using(database).filter(status="accepted").update(status="resolved")
    CustomRequest.objects.using(database).filter(status="denied").update(status="postponed")


def restore_custom_request_statuses(apps, schema_editor):
    CustomRequest = apps.get_model("store", "CustomRequest")
    database = schema_editor.connection.alias
    CustomRequest.objects.using(database).filter(status="resolved").update(status="accepted")
    CustomRequest.objects.using(database).filter(status="postponed").update(status="denied")


class Migration(migrations.Migration):

    dependencies = [
        ("store", "0026_refresh_review_ratings"),
    ]

    operations = [
        migrations.RunPython(update_custom_request_statuses, restore_custom_request_statuses),
        migrations.AlterField(
            model_name="customrequest",
            name="status",
            field=models.CharField(
                choices=[("pending", "Pending"), ("resolved", "Resolved"), ("postponed", "Postponed")],
                default="pending",
                max_length=10,
            ),
        ),
    ]
