import os
from io import BytesIO

from django.core.files.base import ContentFile
from PIL import Image, ImageOps


def convert_to_webp(instance, field_name, max_dim=1920, quality=82):
    """
    Convert the image in `instance.<field_name>` to WebP in place.

    - Resizes so the longest edge is at most `max_dim` (preserves aspect ratio).
    - Applies EXIF rotation (phone photos come out upright).
    - Flattens transparency onto white (WebP supports alpha, but our
      designs don't use it, and RGB compresses better).
    - Fails silently — if anything goes wrong, the original file is kept.

    Returns the old field name if a conversion happened, else None.
    """
    field = getattr(instance, field_name)
    if not field or not getattr(field, "name", None):
        return None
    if field.name.lower().endswith(".webp"):
        return None

    old_name = field.name

    try:
        field.seek(0)
        img = Image.open(field)

        # Upright based on EXIF orientation
        img = ImageOps.exif_transpose(img)

        # Flatten transparency onto white
        if img.mode in ("RGBA", "LA", "P"):
            if img.mode == "P":
                img = img.convert("RGBA")
            background = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "RGBA":
                background.paste(img, mask=img.split()[-1])
            else:
                background.paste(img)
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")

        # Downscale if oversized
        if max(img.size) > max_dim:
            img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

        # Encode WebP in memory
        output = BytesIO()
        img.save(output, format="WEBP", quality=quality, method=6)
        output.seek(0)

        base = os.path.splitext(os.path.basename(old_name))[0]
        new_name = f"{os.path.dirname(old_name)}/{base}.webp".lstrip("/")

        # Replace the field's file object — Django saves it on model save
        setattr(instance, field_name, ContentFile(output.read(), name=new_name))
        return old_name
    except Exception:
        return None