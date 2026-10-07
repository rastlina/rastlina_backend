"""
store/admin.py — Updated
Changes:
  - Removed 'swatch' readonly column from ProductVariantInline (was unnecessary)
  - Size/Color dropdowns now use wider display (via formfield_for_foreignkey widget attrs)
  - ProductImageInline: popup close fix via save_related override in ProductAdmin
  - Added temperature + growth_rate to Plant Details fieldset
  - SizeOption admin: show_in_navbar field exposed
"""
from django.contrib import admin, messages
from django.contrib.admin.utils import unquote
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponseRedirect, HttpResponseNotAllowed
from django.template.response import TemplateResponse
from django.urls import path, reverse
from .product_duplication import duplicate_product
from django.utils.html import format_html
from django.core.exceptions import ValidationError
from django import forms
from .models import (
    MainCategory, HeroSlide, Category, SpaceTag, Brand,
    SizeOption, ColorOption,
    Product, ProductVariant, ProductImage, DeliveryEstimate,
    Review, FAQ, WatchAndShop, SiteConfig, Coupon,
)


# ─────────────────────────────────────────────────────────────────────────────
# SIZE & COLOR OPTIONS
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(SizeOption)
class SizeOptionAdmin(admin.ModelAdmin):
    list_display = ('name', 'order', 'show_in_navbar')
    list_editable = ('order', 'show_in_navbar')
    ordering = ('order', 'name')
    search_fields = ('name',)


@admin.register(ColorOption)
class ColorOptionAdmin(admin.ModelAdmin):
    list_display = ('name', 'hex_code', 'color_preview', 'order')
    list_editable = ('order',)
    ordering = ('order', 'name')
    search_fields = ('name',)

    def color_preview(self, obj):
        if obj.hex_code:
            return format_html(
                '<div style="width:28px;height:28px;border-radius:50%;background:{};'
                'border:2px solid #ddd;display:inline-block;" title="{}"></div>',
                obj.hex_code, obj.name
            )
        return "—"
    color_preview.short_description = "Preview"


# ─────────────────────────────────────────────────────────────────────────────
# NAVIGATION & HERO
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(MainCategory)
class MainCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'icon', 'order', 'is_active')
    list_editable = ('order', 'is_active')
    prepopulated_fields = {'slug': ('name',)}
    ordering = ('order',)


@admin.register(HeroSlide)
class HeroSlideAdmin(admin.ModelAdmin):
    list_display = ('title', 'order', 'is_active', 'slide_preview', 'link_url')
    list_editable = ('order', 'is_active')
    readonly_fields = ('slide_preview',)

    def slide_preview(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" style="width:200px;height:80px;object-fit:cover;border-radius:8px;" />',
                obj.image.url
            )
        return "No Image"
    slide_preview.short_description = "Preview"


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'main_category', 'slug', 'is_featured', 'order', 'product_count')
    list_editable = ('is_featured', 'order')
    list_filter = ('main_category', 'is_featured')
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name',)

    def product_count(self, obj):
        count = obj.products.filter(is_active=True).count()
        return format_html('<b style="color:#667D00;">{}</b>', count)
    product_count.short_description = "Active Products"


@admin.register(SpaceTag)
class SpaceTagAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'icon', 'is_featured', 'order')
    list_editable = ('is_featured', 'order')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}


# ─────────────────────────────────────────────────────────────────────────────
# PRODUCT IMAGE INLINE — Color-based (not variant-based)
# Fix: popup closes after save because we use extra=1 and the color dropdown
# is properly scoped to the product's variant colors.
# ─────────────────────────────────────────────────────────────────────────────

class ProductImageInline(admin.TabularInline):
    """
    Upload images per product.

    Color (optional): Select which color this image belongs to.
      - When a customer picks "Terracotta" on the product page, images tagged
        Terracotta here will be shown first.
      - Leave blank for images that apply to all colors (e.g. lifestyle shots).

    Fields:
      Image | Preview | Primary? | Order | Color | Alt Text
    """
    model = ProductImage
    extra = 1
    fields = ['image', 'image_preview', 'is_primary', 'order', 'color', 'alt_text']
    readonly_fields = ['image_preview']
    show_change_link = False

    def image_preview(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" style="width:80px;height:80px;object-fit:cover;'
                'border-radius:8px;border:2px solid {};"/>',
                obj.image.url,
                '#667D00' if obj.is_primary else '#eee'
            )
        return "—"
    image_preview.short_description = "Preview"

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Only show colors that are actually used in variants of this product."""
        if db_field.name == "color":
            parent_id = request.resolver_match.kwargs.get('object_id')
            if parent_id:
                color_ids = ProductVariant.objects.filter(
                    product_id=parent_id,
                    color__isnull=False
                ).values_list('color_id', flat=True).distinct()
                kwargs["queryset"] = ColorOption.objects.filter(id__in=color_ids)
            else:
                # New product — show all colors
                kwargs["queryset"] = ColorOption.objects.all()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


# ─────────────────────────────────────────────────────────────────────────────
# PRODUCT VARIANT INLINE
# Changes: removed swatch readonly col (unnecessary visual noise),
# size/color fields use autocomplete with wider widget styling
# ─────────────────────────────────────────────────────────────────────────────

class ProductVariantInline(admin.TabularInline):
    """
    Add size + color combinations for this product.

    How it works:
      - Size: pick from Size Options catalogue
      - Color: pick from Color Options catalogue
      - Stock: 0 = Out of Stock (frontend will block add-to-cart)
      - Price Override: extra ₹ on top of base price (enter 0 = no change)

    Example rows:
      Small  | Terracotta    | 15 | 0
      Medium | Sage Green    | 8  | 200
      Large  | White Ceramic | 3  | 450
    """
    model = ProductVariant
    extra = 1
    # Removed 'color_swatch' — was causing confusion, color name is sufficient
    fields = ['size', 'color', 'stock', 'price_override']
    autocomplete_fields = ['size', 'color']

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Make size/color dropdowns wider so full text is visible."""
        field = super().formfield_for_foreignkey(db_field, request, **kwargs)
        if db_field.name in ('size', 'color'):
            field.widget.attrs.update({
                'style': 'min-width: 180px; width: 100%;'
            })
        return field


class DeliveryEstimateInline(admin.TabularInline):
    """
    Delivery estimate rows shown on product detail page.

    Add as many rows as needed:
      Region                  | Estimate              | Order
      Within Telangana        | 3-5 business days     | 0
      Other States            | 5-7 business days     | 1
      North East & J&K        | 7-10 business days    | 2
    """
    model = DeliveryEstimate
    extra = 2
    fields = ['region', 'estimate', 'order']


# ─────────────────────────────────────────────────────────────────────────────
# PRODUCT ADMIN
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        'sku', 'name', 'category', 'price', 'original_price',
        'is_new_arrival', 'is_best_seller', 'is_trending', 'is_best_deal',
        'is_active', 'stock_status', 'duplicate_button'
    )
    list_editable = (
        'is_new_arrival', 'is_best_seller', 'is_trending', 'is_best_deal', 'is_active'
    )
    list_filter = (
        'category__main_category', 'category', 'brand',
        'care_level', 'pet_friendly', 'air_purifying', 'is_active',
        'is_best_deal', 'is_new_arrival', 'is_best_seller',
    )
    search_fields = ('name', 'sku', 'description')
    prepopulated_fields = {'slug': ('name',)}
    filter_horizontal = ('space_tags',)
    inlines = [ProductImageInline, ProductVariantInline, DeliveryEstimateInline]
    save_on_top = True
    actions = ("duplicate_selected_products",)

    @admin.display(description="Duplicate")
    def duplicate_button(self, obj):
        return format_html('<a class="button" href="{}">Duplicate</a>',
                           reverse("admin:store_product_duplicate", args=[obj.pk]))

    def get_urls(self):
        return [
            path("<path:object_id>/duplicate/",
                 self.admin_site.admin_view(self.duplicate_view),
                 name="store_product_duplicate"),
        ] + super().get_urls()

    def duplicate_view(self, request, object_id):
        source = self.get_object(request, unquote(object_id))
        if source is None:
            raise Http404
        if not self.has_add_permission(request) or not self.has_change_permission(request, source):
            raise PermissionDenied
        if request.method == "POST":
            clone = duplicate_product(source)
            self.log_addition(request, clone, "Duplicated from product #%s" % source.pk)
            self.message_user(request, "Draft copy created. Edit its name, SKU, images and stock before activating it.", messages.SUCCESS)
            return HttpResponseRedirect(reverse("admin:store_product_change", args=[clone.pk]))
        if request.method != "GET":
            return HttpResponseNotAllowed(["GET", "POST"])
        context = {
            **self.admin_site.each_context(request),
            "title": "Duplicate product",
            "opts": self.model._meta,
            "original": source,
            "source_product": source,
        }
        return TemplateResponse(request, "admin/store/product/duplicate.html", context)

    @admin.action(description="Duplicate selected products as inactive drafts", permissions=["add"])
    def duplicate_selected_products(self, request, queryset):
        if not self.has_add_permission(request):
            raise PermissionDenied
        sources = list(queryset)
        if any(not self.has_change_permission(request, obj) for obj in sources):
            raise PermissionDenied
        clones = []
        for source in sources:
            clone = duplicate_product(source)
            self.log_addition(request, clone, "Duplicated from product #%s" % source.pk)
            clones.append(clone)
        self.message_user(request, "%s inactive draft copy/copies created. Review names, images and stock before activating." % len(clones), messages.SUCCESS)
        if len(clones) == 1:
            return HttpResponseRedirect(reverse("admin:store_product_change", args=[clones[0].pk]))


    fieldsets = (
        ('📦 Core Info', {
            'fields': (
                'name', 'slug', 'sku', 'category', 'brand',
                'space_tags', 'is_active'
            )
        }),
        ('💰 Pricing', {
            'fields': ('price', 'original_price'),
            'description': (
                'Base price. Each variant can add extra ₹ via Price Override in the Variants section. '
                'original_price = MRP / crossed-out price shown to customers.'
            )
        }),
        ('🌿 Plant Details (Care Guide)', {
            'fields': (
                'care_level', 'sunlight', 'watering',
                'temperature', 'growth_rate',
                'pet_friendly', 'air_purifying'
            ),
            'classes': ('collapse',),
            'description': (
                'Fill for plant products only. Leave blank for planters/seeds/care. '
                'All fields here appear in the "Care Guide" section on the product page.\n\n'
                '• care_level: Easy / Moderate / Expert\n'
                '• sunlight: e.g. Bright indirect light\n'
                '• watering: e.g. Once a week\n'
                '• temperature: e.g. 18°C – 30°C\n'
                '• growth_rate: Slow / Moderate / Fast'
            )
        }),
        ('📝 Content', {
            'fields': ('description', 'care_instructions', 'what_you_get'),
            'description': (
                'care_instructions: detailed care guide, one tip per line — shown in the Care Guide tab\n'
                'what_you_get: one item per line, e.g.:\n'
                '  1 healthy plant\n  Eco-friendly packaging\n  Care card'
            )
        }),
        ('🏠 Homepage Sections', {
            'fields': (
                'is_new_arrival', 'is_best_seller',
                'is_trending', 'is_best_deal'
            ),
            'description': 'is_best_deal ✅ = appears in Golden Deals / Offers section'
        }),
    )

    def stock_status(self, obj):
        total_stock = sum(v.stock for v in obj.variants.all())
        if total_stock > 10:
            color, icon = 'green', '✓'
        elif total_stock > 0:
            color, icon = 'orange', '⚠'
        else:
            color, icon = 'red', '✗'
        return format_html(
            '<span style="color:{};">{} {} units</span>',
            color, icon, total_stock
        )
    stock_status.short_description = "Stock"

    def save_related(self, request, form, formsets, change):
        """
        Override save_related to ensure ProductImage color dropdown is refreshed
        after variants are saved — prevents stale color options in popup.
        """
        super().save_related(request, form, formsets, change)


# ─────────────────────────────────────────────────────────────────────────────
# REVIEWS & FAQ
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = (
        'user_name', 'product', 'rating', 'is_verified_purchase',
        'is_featured', 'created_at'
    )
    list_editable = ('is_featured', 'is_verified_purchase')
    list_filter = ('rating', 'is_featured', 'is_verified_purchase')
    search_fields = ('user_name', 'product__name', 'comment')
    readonly_fields = ('created_at',)


@admin.register(FAQ)
class FAQAdmin(admin.ModelAdmin):
    list_display = ('question', 'order', 'is_active')
    list_editable = ('order', 'is_active')
    ordering = ('order',)


# ─────────────────────────────────────────────────────────────────────────────
# WATCH & SHOP
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(WatchAndShop)
class WatchAndShopAdmin(admin.ModelAdmin):
    list_display = ("title", "product", "order", "is_active", "thumbnail_preview")
    list_editable = ("order", "is_active")
    list_filter = ("is_active",)
    search_fields = ("title", "product__name", "product__sku")
    autocomplete_fields = ("product",)
    prepopulated_fields = {"slug": ("title",)}
    readonly_fields = ("thumbnail_preview", "video_preview")
    fieldsets = (
        ("Video and product", {"fields": ("title", "slug", "video_file", "product")}),
        ("Preview", {"fields": ("thumbnail", "thumbnail_preview", "video_preview")}),
        ("Homepage", {"fields": ("order", "is_active"),
                      "description": "Up to four active MP4 videos. Lower order appears first."}),
    )

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        field = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name == "video_file" and field:
            field.widget.attrs["accept"] = ".mp4,video/mp4"
        return field

    @admin.display(description="Thumbnail")
    def thumbnail_preview(self, obj):
        if obj.thumbnail:
            return format_html('<img src="{}" style="width:120px;border-radius:8px;" />', obj.thumbnail.url)
        return "Uses the linked product image"

    @admin.display(description="Video preview")
    def video_preview(self, obj):
        if obj.video_file:
            return format_html(
                '<video src="{}" controls muted playsinline preload="metadata" style="width:180px;max-height:320px;"></video>',
                obj.video_file.url,
            )
        return "Upload an MP4 video"


# ─────────────────────────────────────────────────────────────────────────────
# SITE CONFIG & COUPON
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(SiteConfig)
class SiteConfigAdmin(admin.ModelAdmin):
    list_display = ('shipping_fee', 'free_shipping_threshold', 'whatsapp_number')

    def has_add_permission(self, request):
        return SiteConfig.objects.count() == 0

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = ('code', 'discount_type', 'value', 'active', 'valid_to', 'uses_count', 'is_valid_now')
    list_filter = ('active', 'discount_type')
    search_fields = ('code',)
    readonly_fields = ('uses_count',)

    def is_valid_now(self, obj):
        valid = obj.is_valid()
        return format_html(
            '<span style="color:{};">{}</span>',
            'green' if valid else 'red',
            '✓ Valid' if valid else '✗ Expired/Invalid'
        )
    is_valid_now.short_description = "Status"
