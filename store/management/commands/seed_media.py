import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Copy missing bundled product and site images into MEDIA_ROOT."

    def handle(self, *args, **options):
        seed_root = Path(settings.BASE_DIR) / "media_seed"
        copied = 0
        for source in seed_root.rglob("*"):
            if not source.is_file():
                continue
            destination = Path(settings.MEDIA_ROOT) / source.relative_to(seed_root)
            if not destination.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                copied += 1
        self.stdout.write(self.style.SUCCESS(f"Copied {copied} missing media file(s)."))
