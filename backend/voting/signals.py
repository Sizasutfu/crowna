from django.db.models.signals import pre_save
from django.dispatch import receiver

from .image_utils import convert_to_webp
from .models import Contest, Contestant


@receiver(pre_save, sender=Contest)
def convert_contest_image(sender, instance, **kwargs):
    convert_to_webp(instance, "image", max_dim=1920, quality=82)


@receiver(pre_save, sender=Contestant)
def convert_contestant_image(sender, instance, **kwargs):
    convert_to_webp(instance, "image", max_dim=800, quality=82)