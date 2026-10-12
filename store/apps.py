from django.apps import AppConfig


class StoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "store"

    def ready(self):
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Group
        from django.db.models.signals import post_save
        from django.dispatch import receiver

        @receiver(post_save, sender=get_user_model())
        def sync_manager_group(sender, instance, **kwargs):
            if instance.is_staff and not instance.is_superuser:
                manager_group, _ = Group.objects.get_or_create(name="Manager")
                instance.groups.add(manager_group)
