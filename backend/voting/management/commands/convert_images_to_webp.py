from django.core.management.base import BaseCommand

from voting.image_utils import convert_to_webp
from voting.models import Contest, Contestant


class Command(BaseCommand):
    help = "Convert existing Contest and Contestant images to WebP."

    def handle(self, *args, **options):
        total = 0
        for model, max_dim, label in [
            (Contest, 1920, "contest"),
            (Contestant, 800, "contestant"),
        ]:
            qs = model.objects.exclude(image="").exclude(image__isnull=True)
            for obj in qs.iterator():
                if obj.image.name.lower().endswith(".webp"):
                    continue

                old_name = obj.image.name
                old_storage = obj.image.storage

                result = convert_to_webp(obj, "image", max_dim=max_dim)
                if result is None:
                    continue

                obj.save(update_fields=["image"])
                total += 1
                self.stdout.write(
                    f"  {label} {obj.pk}: {old_name} → {obj.image.name}"
                )

                # Delete the old file from storage
                try:
                    old_storage.delete(old_name)
                except Exception:
                    pass

        self.stdout.write(self.style.SUCCESS(f"Converted {total} image(s)."))