from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def normalize_custom_request_statuses(apps, schema_editor):
    CustomRequest = apps.get_model("store", "CustomRequest")
    CustomRequest.objects.filter(status__in=["new", "quoted"]).update(status="pending")
    CustomRequest.objects.filter(status__in=["approved", "done"]).update(status="accepted")


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("store", "0018_order_phone_verified"),
    ]

    operations = [
        migrations.AddField(
            model_name="customrequest",
            name="custom_text_color",
            field=models.CharField(default="#111111", max_length=7),
        ),
        migrations.AddField(
            model_name="customrequest",
            name="user",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="custom_requests", to=settings.AUTH_USER_MODEL),
        ),
        migrations.RunPython(normalize_custom_request_statuses, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="customrequest",
            name="status",
            field=models.CharField(choices=[("pending", "Pending"), ("accepted", "Accepted"), ("denied", "Denied")], default="pending", max_length=10),
        ),
    ]
