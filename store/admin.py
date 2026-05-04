from django.contrib import admin
from django.utils.html import format_html
from django.core.exceptions import ValidationError
from .models import (
    MainCategory, Category, SpaceTag, Brand,
    Product, ProductVariant, ProductImage,
    Review, WatchAndShop, SiteConfig, Coupon
)


# ─────────────────────────────────────────────────────────────────────────────
# NAVIGATION STRUCTURE
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(MainCategory)
class MainCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'icon', 'order', 'is_active')
    list_editable = ('order', 'is_active')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'main_category', 'slug', 'is_featured', 'order', 'product_count')
    list_editable = ('is_featured', 'order')
    list_filter = ('main_category', 'is_featured')
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name',)

    def product_count(self, obj):
        return obj.products.filter(is_active=True).count()
    product_count.short_description = "Products"


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
# PRODUCT ADMIN
# ─────────────────────────────────────────────────────────────────────────────

class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1
    fields = ['image', 'image_preview', 'is_primary', 'order', 'variant', 'alt_text']
    readonly_fields = ['image_preview']

    def image_preview(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" style="width:70px;height:70px;object-fit:cover;border-radius:6px;" />',
                obj.image.url
            )
        return "No Image"
    image_preview.short_description = "Preview"


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 1
    fields = ['size', 'color', 'color_hex', 'stock', 'price_override', 'sku_suffix']


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        'sku', 'name', 'category', 'price', 'original_price',
        'is_new_arrival', 'is_best_seller', 'is_trending', 'is_best_deal',
        'is_active', 'stock_status'
    )
    list_editable = (
        'is_new_arrival', 'is_best_seller', 'is_trending', 'is_best_deal', 'is_active'
    )
    list_filter = (
        'category__main_category', 'category', 'brand',
        'care_level', 'pet_friendly', 'air_purifying', 'is_active'
    )
    search_fields = ('name', 'sku', 'description')
    prepopulated_fields = {'slug': ('name',)}
    filter_horizontal = ('space_tags',)
    inlines = [ProductImageInline, ProductVariantInline]

    fieldsets = (
        ('Core Info', {
            'fields': (
                'name', 'slug', 'sku', 'category', 'brand',
                'space_tags', 'is_active'
            )
        }),
        ('Pricing', {
            'fields': ('price', 'original_price')
        }),
        ('Plant Details', {
            'fields': (
                'care_level', 'sunlight', 'watering',
                'pet_friendly', 'air_purifying'
            ),
            'classes': ('collapse',),
            'description': 'Leave blank for non-plant products'
        }),
        ('Content', {
            'fields': ('description', 'highlights', 'care_instructions', 'what_you_get')
        }),
        ('Trust Info', {
            'fields': ('warranty_info', 'return_policy')
        }),
        ('Homepage Toggles', {
            'fields': (
                'is_new_arrival', 'is_best_seller',
                'is_trending', 'is_best_deal', 'is_featured_home'
            )
        }),
    )

    def stock_status(self, obj):
        total_stock = sum(v.stock for v in obj.variants.all())
        if total_stock > 10:
            return format_html('<span style="color:green;">✓ {} in stock</span>', total_stock)
        elif total_stock > 0:
            return format_html('<span style="color:orange;">⚠ {} left</span>', total_stock)
        else:
            return format_html('<span style="color:red;">✗ Out of stock</span>')
    stock_status.short_description = "Stock"


# ─────────────────────────────────────────────────────────────────────────────
# REVIEWS
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = (
        'user_name', 'product', 'rating', 'is_verified_purchase',
        'is_featured', 'image_preview', 'created_at'
    )
    list_editable = ('is_featured',)
    list_filter = ('rating', 'is_featured', 'is_verified_purchase')
    search_fields = ('user_name', 'product__name', 'comment')
    readonly_fields = ('image_preview', 'created_at')

    def image_preview(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" style="width:80px;height:auto;" />',
                obj.image.url
            )
        return "—"


# ─────────────────────────────────────────────────────────────────────────────
# WATCH & SHOP
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(WatchAndShop)
class WatchAndShopAdmin(admin.ModelAdmin):
    list_display = ('title', 'product', 'order', 'is_active', 'thumbnail_preview')
    list_editable = ('order', 'is_active')
    readonly_fields = ('thumbnail_preview',)

    def thumbnail_preview(self, obj):
        if obj.thumbnail:
            return format_html(
                '<img src="{}" style="width:120px;height:auto;border-radius:8px;" />',
                obj.thumbnail.url
            )
        return "No thumbnail"

    def save_model(self, request, obj, form, change):
        try:
            obj.clean()
        except ValidationError as e:
            from django.contrib import messages
            messages.error(request, str(e.message))
            return
        super().save_model(request, obj, form, change)


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
            '✓ Valid' if valid else '✗ Invalid'
        )
    is_valid_now.short_description = "Status"