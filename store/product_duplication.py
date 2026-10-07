"""Create an independent, inactive product copy for editing in the admin."""
import logging
from pathlib import PurePosixPath
from uuid import uuid4

from django.core.files import File
from django.db import transaction

from .models import Product, ProductImage, ProductVariant, DeliveryEstimate

logger = logging.getLogger(__name__)


def duplicate_product(source):
    database = source._state.db or "default"
    written_files = []
    try:
        with transaction.atomic(using=database):
            excluded = {"id", "name", "slug", "sku", "created_at", "updated_at"}
            values = {
                field.attname: getattr(source, field.attname)
                for field in Product._meta.concrete_fields
                if not field.primary_key and field.name not in excluded
            }
            token = uuid4().hex[:12]
            name_length = Product._meta.get_field("name").max_length
            slug_length = Product._meta.get_field("slug").max_length
            sku_length = Product._meta.get_field("sku").max_length
            suffix = "-copy-" + token
            values.update(
                name=source.name[:name_length - 7] + " (copy)",
                slug=source.slug[:slug_length - len(suffix)] + suffix,
                sku=source.sku[:sku_length - len(suffix)] + suffix,
                is_active=False,
                is_new_arrival=False,
                is_best_seller=False,
                is_trending=False,
                is_best_deal=False,
            )
            clone = Product.objects.using(database).create(**values)
            clone.space_tags.set(source.space_tags.all())
            for variant in source.variants.all():
                ProductVariant.objects.using(database).create(
                    product=clone, size_id=variant.size_id, color_id=variant.color_id,
                    stock=variant.stock, price_override=variant.price_override,
                )
            for estimate in source.delivery_estimates.all():
                DeliveryEstimate.objects.using(database).create(
                    product=clone, region=estimate.region,
                    estimate=estimate.estimate, order=estimate.order,
                )
            for image in source.images.all():
                copied = ProductImage(
                    product=clone, color_id=image.color_id, alt_text=image.alt_text,
                    is_primary=image.is_primary, order=image.order,
                )
                if image.image:
                    filename = uuid4().hex + "-" + PurePosixPath(image.image.name).name
                    with image.image.storage.open(image.image.name, "rb") as image_file:
                        copied.image.save(filename, File(image_file), save=False)
                    written_files.append((copied.image.storage, copied.image.name))
                copied.save(using=database)
            # Reviews, orders, carts and Watch & Shop links are never copied.
            return clone
    except Exception:
        # Storage writes do not participate in database transactions.
        for storage, name in written_files:
            try:
                storage.delete(name)
            except Exception:
                logger.exception("Could not clean up a failed duplicate image")
        raise

