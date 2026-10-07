"""One-time import of the four current homepage MP4s into admin-managed records."""
from pathlib import Path

from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from store.models import Product, WatchAndShop


class Command(BaseCommand):
    help = "Import the four supplied MP4 cards into Watch & Shop without overwriting uploaded videos."

    def handle(self, *args, **options):
        root = Path(__file__).resolve().parents[2] / "initial_watch_shop"
        cards = [
            ("Rex Begonia", "rex-begonia"),
            ("Calathea Ornata", "calathea-ornata"),
            ("Aglaonema Suksom Jaipong", "aglaonema-suksom-jaipong"),
            ("Philodendron Moonshine", "philodendron-moonshine"),
        ]
        products = {}
        for title, slug in cards:
            try:
                products[slug] = Product.objects.get(slug=slug, is_active=True)
            except Product.DoesNotExist as exc:
                raise CommandError("Active product not found: " + slug) from exc
            if not (root / (slug + ".mp4")).is_file() or not (root / (slug + ".jpg")).is_file():
                raise CommandError("Initial video or thumbnail missing: " + slug)
        written_files = []
        imported = 0
        try:
            with transaction.atomic():
                # The former Cryptanthus/YouTube card is not part of the new four.
                WatchAndShop.objects.filter(is_active=True, video_file="").exclude(
                    slug__in=[slug for title, slug in cards]
                ).update(is_active=False)
                for order, (title, slug) in enumerate(cards):
                    item = WatchAndShop.objects.filter(slug=slug).first()
                    if item and item.video_file:
                        continue  # Do not overwrite later edits made in the admin.
                    item = item or WatchAndShop(slug=slug)
                    item.title = title
                    item.product = products[slug]
                    item.order = order
                    item.is_active = True
                    item.video_url = ""
                    for field_name, extension in [("video_file", ".mp4"), ("thumbnail", ".jpg")]:
                        field = getattr(item, field_name)
                        source_path = root / (slug + extension)
                        with source_path.open("rb") as handle:
                            field.save(source_path.name, File(handle), save=False)
                        written_files.append((field.storage, field.name))
                    item.full_clean()
                    item.save()
                    imported += 1
        except Exception as exc:
            for storage, name in written_files:
                try:
                    storage.delete(name)
                except Exception:
                    self.stderr.write("Could not remove an unused file: " + name)
            raise CommandError("Initial MP4 import failed; database changes were rolled back.") from exc
        self.stdout.write(self.style.SUCCESS("Imported %s MP4 card(s). Existing uploads were preserved." % imported))

