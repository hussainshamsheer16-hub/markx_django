from django.core.management.base import BaseCommand
from store.models import Category


class Command(BaseCommand):
    help = "Ensure the Pairs storefront category exists."

    def handle(self, *args, **options):
        Category.objects.get_or_create(name="Pairs", defaults={"tagline": "Coordinated shirt and trouser pairs.", "show_on_home": True, "order": 3})
        self.stdout.write(self.style.SUCCESS("Pairs category is ready."))
