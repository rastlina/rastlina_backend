"""
Rastlina Store Models

Navigation Structure:
─────────────────────
Navbar Top Level (Fixed): Plants | Planters | Seeds | Care | Offers | Combos | Bulk
  └── Plants submenu:
      ├── By Size (dynamic from variants): All Plants / Large / Medium / Small
      ├── Shop by Type (dynamic: Category filtered by plant main_category)
      └── Shop by Space (dynamic: UsageTag / SpaceTag)
  └── Planters submenu: (categories under PLANTER main_category)
  └── Seeds submenu:    (categories under SEED main_category)
  └── Care submenu:     (categories under CARE main_category)

Model Hierarchy:
────────────────
MainCategory  →  Category  →  Product  →  ProductVariant (size/color)
                                       →  ProductImage
SpaceTag (shop by space / usage)
Brand (optional for care/planters products)
"""

from django.db import models
from django.utils.text import slugify
from django.utils import timezone
from django.contrib.auth import get_user_model

User = get_user_model()


# ─────────────────────────────────────────────────────────────────────────────
# MAIN CATEGORY (Fixed top-level navbar items)
# ─────────────────────────────────────────────────────────────────────────────

class MainCategory(models.Model):
    """
    Fixed top-level navbar sections.
    Admin creates these once: Plants, Planters, Seeds, Care, Offers, Combos, Bulk
    """
    ICON_CHOICES = [
        ('leaf', '🌿 Leaf'),
        ('pot', '🪴 Pot'),
        ('seedling', '🌱 Seedling'),
        ('spray', '💧 Spray'),
        ('tag', '🏷️ Offers'),
        ('bundle', '📦 Bundle'),
        ('truck', '🚚 Bulk'),
    ]

    name = models.CharField(max_length=100)          # "Plants", "Planters", etc.
    slug = models.SlugField(unique=True, blank=True)
    icon = models.CharField(max_length=50, blank=True, choices=ICON_CHOICES)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['order']
        verbose_name = "Main Category (Navbar)"
        verbose_name_plural = "Main Categories (Navbar)"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


# ─────────────────────────────────────────────────────────────────────────────
# CATEGORY (Dynamic sub-categories inside each main category)
# ─────────────────────────────────────────────────────────────────────────────

class Category(models.Model):
    """
    Dynamic categories managed from admin.
    Examples under Plants main_category: Succulents, Tropical, Air-Purifying, Flowering
    Examples under Planters: Ceramic, Terracotta, Hanging, Self-Watering
    Examples under Seeds: Vegetable, Herb, Flower, Microgreens
    Examples under Care: Fertilizers, Soil, Pesticides, Tools
    """
    main_category = models.ForeignKey(
        MainCategory,
        on_delete=models.CASCADE,
        related_name='categories',
        help_text="Which top-level section does this belong to?"
    )
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True, blank=True)
    image = models.ImageField(upload_to='categories/', null=True, blank=True)
    description = models.TextField(blank=True)
    is_featured = models.BooleanField(
        default=False,
        help_text="Show in 'Explore by Category' on homepage"
    )
    order = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name_plural = "Categories"
        ordering = ['order', 'name']

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.main_category.name} › {self.name}"


# ─────────────────────────────────────────────────────────────────────────────
# SPACE TAG (Shop by Space / Curate your atmosphere)
# ─────────────────────────────────────────────────────────────────────────────

class SpaceTag(models.Model):
    """
    Tags for 'Shop by Space' / 'Curate your atmosphere' section.
    Examples: Living Room, Bedroom, Balcony, Office, Kitchen, Bathroom
    """
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True, blank=True)
    icon = models.CharField(
        max_length=100, blank=True,
        help_text="Lucide icon name e.g. 'sofa', 'bed', 'sun'"
    )
    image = models.ImageField(upload_to='spaces/', null=True, blank=True)
    is_featured = models.BooleanField(
        default=False,
        help_text="Show in 'Curate your atmosphere' on homepage"
    )
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'name']

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


# ─────────────────────────────────────────────────────────────────────────────
# BRAND (Optional — for planters, care products, seeds)
# ─────────────────────────────────────────────────────────────────────────────

class Brand(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True, blank=True)
    logo = models.ImageField(upload_to='brands/', null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


# ─────────────────────────────────────────────────────────────────────────────
# PRODUCT
# ─────────────────────────────────────────────────────────────────────────────

class Product(models.Model):
    """
    Central product model for all types: Plants, Planters, Seeds, Care products.
    
    For Plants:    variants = sizes (Small/Medium/Large), colors = pot colors
    For Planters:  variants = sizes (S/M/L/XL), colors = material colors
    For Seeds:     variants = packet sizes (50g/100g/250g)
    For Care:      variants = volume sizes (250ml/500ml/1L)
    """

    # Core
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True, blank=True)
    sku = models.CharField(max_length=50, unique=True, help_text="e.g. PLT-001, PLN-002")
    category = models.ForeignKey(
        Category, on_delete=models.CASCADE, related_name='products'
    )
    brand = models.ForeignKey(
        Brand, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='products',
        help_text="Optional — mainly for planters/care/seeds"
    )
    space_tags = models.ManyToManyField(
        SpaceTag, blank=True, related_name='products',
        help_text="Which spaces is this plant/planter suited for?"
    )

    # Pricing
    price = models.DecimalField(max_digits=10, decimal_places=2)
    original_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="MRP / crossed-out price"
    )

    # Plant-specific fields (blank for non-plant products)
    care_level = models.CharField(
        max_length=50, blank=True,
        choices=[
            ('easy', 'Easy Care'),
            ('moderate', 'Moderate'),
            ('expert', 'Expert'),
        ],
        help_text="For plants: Easy / Moderate / Expert"
    )
    sunlight = models.CharField(
        max_length=100, blank=True,
        help_text="e.g. 'Bright indirect light', 'Low light'"
    )
    watering = models.CharField(
        max_length=100, blank=True,
        help_text="e.g. 'Once a week', 'When top inch is dry'"
    )
    pet_friendly = models.BooleanField(
        null=True, blank=True,
        help_text="Is this plant safe for pets? (plants only)"
    )
    air_purifying = models.BooleanField(
        default=False,
        help_text="Is this an air-purifying plant?"
    )

    # Content
    description = models.TextField(blank=True)
    highlights = models.TextField(
        blank=True,
        help_text="One highlight per line. e.g:\nPurifies air\nLow maintenance"
    )
    care_instructions = models.TextField(
        blank=True,
        help_text="Detailed care guide — one tip per line"
    )

    # Packaging & Delivery info
    what_you_get = models.TextField(
        blank=True,
        help_text="What's included — one item per line. e.g:\n1 healthy plant\nEco-friendly packaging"
    )

    # Trust badges per product (override global)
    warranty_info = models.CharField(
        max_length=200, blank=True,
        help_text="e.g. '7-day healthy plant guarantee'"
    )
    return_policy = models.CharField(
        max_length=200, blank=True,
        help_text="e.g. 'Damaged on arrival? We'll replace it.'"
    )

    # Homepage section toggles
    is_new_arrival = models.BooleanField(default=False)
    is_best_seller = models.BooleanField(default=False)
    is_trending = models.BooleanField(default=False)
    is_best_deal = models.BooleanField(default=False)
    is_featured_home = models.BooleanField(
        default=False,
        help_text="Show on homepage hero / featured section"
    )
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.sku} — {self.name}"

    @property
    def main_category(self):
        return self.category.main_category

    @property
    def primary_image_url(self):
        img = self.images.filter(is_primary=True).first() or self.images.first()
        return img.image.url if img else None


# ─────────────────────────────────────────────────────────────────────────────
# PRODUCT VARIANT (Size + Color combinations with stock)
# ─────────────────────────────────────────────────────────────────────────────

class ProductVariant(models.Model):
    """
    Represents a specific combination of size + color for a product.
    
    Plant examples:
      - Small / Green Pot
      - Medium / Terracotta Pot
      - Large / White Ceramic
    
    Planter examples:
      - S / Matte Black
      - M / Sage Green
    
    Seeds/Care examples:
      - 50g Pack / N/A
      - 500ml / N/A
    """
    SIZE_CHOICES = [
        # Plants
        ('small', 'Small'),
        ('medium', 'Medium'),
        ('large', 'Large'),
        ('xl', 'Extra Large'),
        # Seeds / Care
        ('25g', '25g'),
        ('50g', '50g'),
        ('100g', '100g'),
        ('250g', '250g'),
        ('250ml', '250ml'),
        ('500ml', '500ml'),
        ('1l', '1 Litre'),
        # Generic
        ('standard', 'Standard'),
        ('s', 'S'),
        ('m', 'M'),
        ('l', 'L'),
        ('xl', 'XL'),
    ]

    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name='variants'
    )
    size = models.CharField(
        max_length=50,
        choices=SIZE_CHOICES,
        default='standard',
        help_text="Size of this variant"
    )
    color = models.CharField(
        max_length=100, blank=True,
        help_text="Color name e.g. 'Terracotta', 'Sage Green', 'White Ceramic'"
    )
    color_hex = models.CharField(
        max_length=7, blank=True,
        help_text="Hex color code e.g. #E07B54 — shown as color swatch on frontend"
    )
    stock = models.PositiveIntegerField(default=0)
    price_override = models.DecimalField(
        max_digits=10, decimal_places=2, default=0.00,
        help_text="Extra amount added to base price. 0 = same as base price."
    )
    sku_suffix = models.CharField(
        max_length=20, blank=True,
        help_text="Optional variant-level SKU suffix e.g. -SM-TER"
    )

    class Meta:
        unique_together = ('product', 'size', 'color')
        ordering = ['size', 'color']

    def __str__(self):
        color_str = f" / {self.color}" if self.color else ""
        return f"{self.product.sku} | {self.get_size_display()}{color_str}"

    @property
    def final_price(self):
        return float(self.product.price + self.price_override)

    @property
    def final_original_price(self):
        if self.product.original_price:
            return float(self.product.original_price + self.price_override)
        return None

    @property
    def in_stock(self):
        return self.stock > 0


# ─────────────────────────────────────────────────────────────────────────────
# PRODUCT IMAGE
# ─────────────────────────────────────────────────────────────────────────────

class ProductImage(models.Model):
    """
    Multiple images per product.
    Can be linked to a specific variant (e.g. green pot vs terracotta pot image).
    """
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name='images'
    )
    variant = models.ForeignKey(
        ProductVariant, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='images',
        help_text="Link this image to a specific variant (optional)"
    )
    image = models.ImageField(upload_to='products/')
    alt_text = models.CharField(max_length=200, blank=True)
    is_primary = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f"Image for {self.product.sku}"


# ─────────────────────────────────────────────────────────────────────────────
# REVIEW
# ─────────────────────────────────────────────────────────────────────────────

class Review(models.Model):
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name='reviews'
    )
    user = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='reviews'
    )
    user_name = models.CharField(max_length=100)    # Cached display name
    rating = models.IntegerField(choices=[(i, i) for i in range(1, 6)])
    title = models.CharField(max_length=200, blank=True)
    comment = models.TextField()
    image = models.ImageField(upload_to='reviews/', null=True, blank=True)
    variant_info = models.CharField(
        max_length=200, blank=True,
        help_text="e.g. 'Medium / Terracotta Pot'"
    )
    is_verified_purchase = models.BooleanField(default=False)
    is_featured = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user_name} — {self.product.name} ({self.rating}★)"


# ─────────────────────────────────────────────────────────────────────────────
# WATCH AND SHOP (Video section on homepage)
# ─────────────────────────────────────────────────────────────────────────────

class WatchAndShop(models.Model):
    """
    'Watch and Shop' section on homepage.
    Up to 4 videos. Each has thumbnail + linked product.
    """
    title = models.CharField(max_length=200)
    video_url = models.URLField(
        help_text="YouTube/Vimeo embed URL or direct video URL"
    )
    thumbnail = models.ImageField(
        upload_to='watch_shop/',
        help_text="Thumbnail shown before video plays (also shown in cart if linked)"
    )
    product = models.ForeignKey(
        Product, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='watch_videos',
        help_text="Link to a product for 'Shop Now' button"
    )
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['order']
        verbose_name = "Watch & Shop Video"
        verbose_name_plural = "Watch & Shop Videos"

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.is_active and WatchAndShop.objects.filter(
            is_active=True
        ).exclude(pk=self.pk).count() >= 4:
            raise ValidationError("Maximum 4 active Watch & Shop videos allowed.")

    def __str__(self):
        return self.title


# ─────────────────────────────────────────────────────────────────────────────
# SITE CONFIG
# ─────────────────────────────────────────────────────────────────────────────

class SiteConfig(models.Model):
    """Global site settings — only one instance"""
    shipping_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    free_shipping_threshold = models.DecimalField(
        max_digits=10, decimal_places=2, default=999.00
    )
    tax_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    whatsapp_number = models.CharField(
        max_length=20, default='919XXXXXXXXXX',
        help_text="Include country code, no + sign. e.g. 919876543210"
    )
    instagram_url = models.URLField(blank=True)
    facebook_url = models.URLField(blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)

    class Meta:
        verbose_name = "Site Configuration"
        verbose_name_plural = "Site Configuration"

    def __str__(self):
        return "Site Configuration"


# ─────────────────────────────────────────────────────────────────────────────
# COUPON
# ─────────────────────────────────────────────────────────────────────────────

class Coupon(models.Model):
    DISCOUNT_CHOICES = [
        ('percentage', 'Percentage'),
        ('fixed', 'Fixed Amount'),
    ]
    code = models.CharField(max_length=50, unique=True)
    discount_type = models.CharField(max_length=20, choices=DISCOUNT_CHOICES)
    value = models.DecimalField(max_digits=10, decimal_places=2)
    min_order_value = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    valid_from = models.DateTimeField()
    valid_to = models.DateTimeField()
    active = models.BooleanField(default=True)
    usage_limit = models.IntegerField(default=100)
    uses_count = models.IntegerField(default=0)

    def is_valid(self):
        now = timezone.now()
        return (
            self.active and
            self.valid_from <= now <= self.valid_to and
            self.uses_count < self.usage_limit
        )

    def __str__(self):
        return f"{self.code} ({self.discount_type} — {self.value})"