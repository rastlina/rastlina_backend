"""
store/serializers.py — Updated
ProductImageSerializer now exposes color_id, color_name, color_hex
(not variant FK) so the frontend can do color→image mapping.
"""
from rest_framework import serializers
from django.db.models import Avg
from .models import (
    MainCategory, HeroSlide, Category, SpaceTag, Brand,
    SizeOption, ColorOption,
    Product, ProductVariant, ProductImage, DeliveryEstimate,
    Review, FAQ, WatchAndShop, SiteConfig, Coupon,
)


# ─────────────────────────────────────────────────────────────────────────────
# NAVIGATION & HERO
# ─────────────────────────────────────────────────────────────────────────────

class MainCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = MainCategory
        fields = ['id', 'name', 'slug', 'icon', 'order']


class HeroSlideSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()

    class Meta:
        model = HeroSlide
        fields = ['id', 'image',  'link_url', 'order']

    def get_image(self, obj):
        if obj.image:
            request = self.context.get('request')
            return request.build_absolute_uri(obj.image.url) if request else obj.image.url
        return None


class CategorySerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()
    main_category_name = serializers.CharField(source='main_category.name', read_only=True)
    main_category_slug = serializers.CharField(source='main_category.slug', read_only=True)
    product_count = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = [
            'id', 'name', 'slug', 'image', 'description', 'is_featured', 'order',
            'main_category_name', 'main_category_slug', 'product_count',
        ]

    def get_image(self, obj):
        if obj.image:
            request = self.context.get('request')
            return request.build_absolute_uri(obj.image.url) if request else obj.image.url
        return None

    def get_product_count(self, obj):
        return obj.products.filter(is_active=True).count()


class SpaceTagSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()

    class Meta:
        model = SpaceTag
        fields = ['id', 'name', 'slug', 'icon', 'image', 'is_featured', 'order']

    def get_image(self, obj):
        if obj.image:
            request = self.context.get('request')
            return request.build_absolute_uri(obj.image.url) if request else obj.image.url
        return None


class BrandSerializer(serializers.ModelSerializer):
    class Meta:
        model = Brand
        fields = ['id', 'name', 'slug']


# ─────────────────────────────────────────────────────────────────────────────
# SIZE & COLOR OPTION SERIALIZERS
# ─────────────────────────────────────────────────────────────────────────────

class SizeOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = SizeOption
        fields = ['id', 'name', 'order']


class ColorOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ColorOption
        fields = ['id', 'name', 'hex_code', 'order']


# ─────────────────────────────────────────────────────────────────────────────
# PRODUCT IMAGE — Now exposes color FK fields (not variant FK)
# ─────────────────────────────────────────────────────────────────────────────

class ProductImageSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()
    # Color fields for frontend image-switching when a color is selected
    color_id = serializers.IntegerField(source='color.id', read_only=True, default=None)
    color_name = serializers.CharField(source='color.name', read_only=True, default=None)
    color_hex = serializers.CharField(source='color.hex_code', read_only=True, default=None)

    class Meta:
        model = ProductImage
        fields = ['id', 'image', 'alt_text', 'is_primary', 'order',
                  'color_id', 'color_name', 'color_hex']

    def get_image(self, obj):
        if obj.image:
            request = self.context.get('request')
            return request.build_absolute_uri(obj.image.url) if request else obj.image.url
        return None


# ─────────────────────────────────────────────────────────────────────────────
# PRODUCT VARIANT
# ─────────────────────────────────────────────────────────────────────────────

class ProductVariantSerializer(serializers.ModelSerializer):
    final_price = serializers.ReadOnlyField()
    final_original_price = serializers.ReadOnlyField()
    in_stock = serializers.ReadOnlyField()
    size_name = serializers.ReadOnlyField()
    color_name = serializers.ReadOnlyField()
    color_hex = serializers.ReadOnlyField()
    size_id = serializers.IntegerField(source='size.id', read_only=True)
    color_id = serializers.IntegerField(source='color.id', read_only=True, default=None)

    class Meta:
        model = ProductVariant
        fields = [
            'id', 'size_id', 'size_name', 'color_id', 'color_name', 'color_hex',
            'stock', 'price_override', 'final_price', 'final_original_price', 'in_stock',
        ]


# ─────────────────────────────────────────────────────────────────────────────
# DELIVERY ESTIMATE
# ─────────────────────────────────────────────────────────────────────────────

class DeliveryEstimateSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeliveryEstimate
        fields = ['id', 'region', 'estimate', 'order']


# ─────────────────────────────────────────────────────────────────────────────
# REVIEW
# ─────────────────────────────────────────────────────────────────────────────

class ReviewSerializer(serializers.ModelSerializer):
    date = serializers.SerializerMethodField()
    user_name = serializers.CharField(read_only=True)

    class Meta:
        model = Review
        fields = [
            'id', 'user_name', 'rating', 'title', 'comment',
            'variant_info', 'is_verified_purchase', 'is_featured', 'date',
        ]

    def get_date(self, obj):
        from django.utils.timesince import timesince
        return f"{timesince(obj.created_at).split(',')[0]} ago"


# ─────────────────────────────────────────────────────────────────────────────
# FAQ
# ─────────────────────────────────────────────────────────────────────────────

class FAQSerializer(serializers.ModelSerializer):
    class Meta:
        model = FAQ
        fields = ['id', 'question', 'answer', 'order']


# ─────────────────────────────────────────────────────────────────────────────
# PRODUCT — LIST
# ─────────────────────────────────────────────────────────────────────────────

class ProductListSerializer(serializers.ModelSerializer):
    images = ProductImageSerializer(many=True, read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    category_slug = serializers.CharField(source='category.slug', read_only=True)
    main_category_name = serializers.CharField(
        source='category.main_category.name', read_only=True)
    main_category_slug = serializers.CharField(
        source='category.main_category.slug', read_only=True)
    brand_name = serializers.SerializerMethodField()
    space_tags = SpaceTagSerializer(many=True, read_only=True)
    review_count = serializers.SerializerMethodField()
    average_rating = serializers.SerializerMethodField()
    discount_percentage = serializers.SerializerMethodField()
    available_sizes = serializers.SerializerMethodField()
    available_colors = serializers.SerializerMethodField()
    in_stock = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            'id', 'name', 'slug', 'sku',
            'category_name', 'category_slug',
            'main_category_name', 'main_category_slug',
            'brand_name', 'price', 'original_price', 'discount_percentage',
            'care_level', 'pet_friendly', 'air_purifying',
            'space_tags', 'images',
            'is_new_arrival', 'is_best_seller', 'is_trending', 'is_best_deal',
            'review_count', 'average_rating',
            'available_sizes', 'available_colors', 'in_stock',
        ]

    def get_brand_name(self, obj):
        return obj.brand.name if obj.brand else None

    def get_review_count(self, obj):
        return obj.reviews.count()

    def get_average_rating(self, obj):
        avg = obj.reviews.aggregate(Avg('rating'))['rating__avg']
        return round(avg, 1) if avg else 0

    def get_discount_percentage(self, obj):
        if obj.original_price and obj.original_price > obj.price:
            return round(((obj.original_price - obj.price) / obj.original_price) * 100)
        return 0

    def get_available_sizes(self, obj):
        sizes = obj.variants.select_related('size').values(
            'size__id', 'size__name', 'size__order'
        ).distinct().order_by('size__order')
        return [{'id': s['size__id'], 'name': s['size__name']} for s in sizes]

    def get_available_colors(self, obj):
        colors = obj.variants.filter(color__isnull=False).select_related('color').values(
            'color__id', 'color__name', 'color__hex_code', 'color__order'
        ).distinct().order_by('color__order')
        return [
            {'id': c['color__id'], 'name': c['color__name'], 'hex_code': c['color__hex_code']}
            for c in colors
        ]

    def get_in_stock(self, obj):
        return obj.variants.filter(stock__gt=0).exists()


# ─────────────────────────────────────────────────────────────────────────────
# PRODUCT — DETAIL
# ─────────────────────────────────────────────────────────────────────────────

class ProductDetailSerializer(ProductListSerializer):
    variants = ProductVariantSerializer(many=True, read_only=True)
    reviews = ReviewSerializer(many=True, read_only=True)
    delivery_estimates = DeliveryEstimateSerializer(many=True, read_only=True)
    care_instructions_list = serializers.SerializerMethodField()
    what_you_get_list = serializers.SerializerMethodField()

    class Meta(ProductListSerializer.Meta):
        fields = ProductListSerializer.Meta.fields + [
            'description',
            'care_instructions_list', 'what_you_get_list',
            'sunlight', 'watering', 'temperature','growth_rate',
            'delivery_estimates',
            'variants', 'reviews',
        ]

    def get_care_instructions_list(self, obj):
        if not obj.care_instructions:
            return []
        return [c.strip() for c in obj.care_instructions.split('\n') if c.strip()]

    def get_what_you_get_list(self, obj):
        if not obj.what_you_get:
            return []
        return [w.strip() for w in obj.what_you_get.split('\n') if w.strip()]


# ─────────────────────────────────────────────────────────────────────────────
# PRODUCT — SEARCH
# ─────────────────────────────────────────────────────────────────────────────

class ProductSearchSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()
    category_name = serializers.CharField(source='category.name', read_only=True)
    main_category_slug = serializers.CharField(
        source='category.main_category.slug', read_only=True)
    discount_percentage = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            'id', 'name', 'slug', 'price', 'original_price',
            'image', 'category_name', 'main_category_slug', 'discount_percentage',
        ]

    def get_image(self, obj):
        primary = (
            obj.images.filter(is_primary=True).order_by('order', 'id').first()
            or obj.images.order_by('order', 'id').first()
)
        if primary:
            request = self.context.get('request')
            return request.build_absolute_uri(primary.image.url) if request else primary.image.url
        return None

    def get_discount_percentage(self, obj):
        if obj.original_price and obj.original_price > obj.price:
            return round(((obj.original_price - obj.price) / obj.original_price) * 100)
        return 0


# ─────────────────────────────────────────────────────────────────────────────
class WatchAndShopSerializer(serializers.ModelSerializer):
    product_slug = serializers.CharField(source="product.slug", read_only=True)
    video_url = serializers.SerializerMethodField()
    thumbnail = serializers.SerializerMethodField()

    def get_video_url(self, obj):
        if not obj.video_file:
            return ""
        request = self.context.get("request")
        url = obj.video_file.url
        return request.build_absolute_uri(url) if request else url

    def get_thumbnail(self, obj):
        request = self.context.get("request")
        if obj.thumbnail:
            url = obj.thumbnail.url
        elif obj.product_id:
            image = obj.product.images.filter(is_primary=True).order_by("order", "id").first()
            image = image or obj.product.images.order_by("order", "id").first()
            if not image:
                return ""
            url = image.image.url
        else:
            return ""
        return request.build_absolute_uri(url) if request else url

    class Meta:
        model = WatchAndShop
        fields = ["id", "title", "slug", "video_url", "thumbnail",
                  "order", "is_active", "product_slug"]


# ─────────────────────────────────────────────────────────────────────────────
# SITE CONFIG & COUPON
# ─────────────────────────────────────────────────────────────────────────────

class SiteConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = SiteConfig
        fields = '__all__'


# ─────────────────────────────────────────────────────────────────────────────
# NAVBAR (aggregated)
# ─────────────────────────────────────────────────────────────────────────────

class NavbarDataSerializer(serializers.ModelSerializer):
    categories = CategorySerializer(many=True, read_only=True)

    class Meta:
        model = MainCategory
        fields = ['id', 'name', 'slug', 'icon', 'order', 'categories']

# ─────────────────────────────────────────────────────────────────────────────
# COUPON
# ─────────────────────────────────────────────────────────────────────────────

class CouponSerializer(serializers.ModelSerializer):
    class Meta:
        model = Coupon
        fields = [
            'code',
            'discount_type',
            'value',
            'min_order_value',
        ]
