from pathlib import Path

from django.utils.text import slugify


def image_upload_to_institute(instance, filename):
    """
    Store uploads under:
        <institute_slug>/<symbol_number>_<timestamp>.<ext>
    or fall back to "no-institute/" if none set.
    """
    # slugify the institute name, fall back if missing
    if instance.institute and instance.institute.name:
        inst_slug = slugify(instance.institute.name)
    else:
        inst_slug = "no-institute"

    # you can also incorporate symbol_number or timestamp if you like
    path = Path(filename)
    ext = path.suffix
    new_filename = f"profile_photos/{instance.symbol_number}{ext}"

    return str(Path(inst_slug) / new_filename)


def fingerprint_upload_to_institute(instance, filename):
    """
    Store uploads under:
        <institute_slug>/<symbol_number>_<timestamp>.<ext>
    or fall back to "no-institute/" if none set.
    """
    # slugify the institute name, fall back if missing
    if instance.institute and instance.institute.name:
        inst_slug = slugify(instance.institute.name)
    else:
        inst_slug = "no-institute"

    # you can also incorporate symbol_number or timestamp if you like
    path = Path(filename)
    ext = path.suffix
    new_filename = f"fingerprints/{instance.symbol_number}{ext}"

    return str(Path(inst_slug) / new_filename)
