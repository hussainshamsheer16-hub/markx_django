from django.contrib.auth.models import Group
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create the Manager role group and assign existing staff users to it."

    def handle(self, *args, **options):
        group, created = Group.objects.get_or_create(name="Manager")
        group.user_set.add(*get_user_model().objects.filter(is_staff=True, is_superuser=False))
        message = "Created Manager group." if created else "Manager group is ready."
        self.stdout.write(self.style.SUCCESS(message))
