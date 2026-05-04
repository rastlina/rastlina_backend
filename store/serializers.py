from rest_framework import serializers
from django.db.models import Avg, Count
from .models import (
    MainCategory, Category, SpaceTag, Brand,
    Product, ProductVariant, ProductImage,
    Review, WatchAndShop, SiteConfig, Coupon
)


# ─────────────────────────────────────────────────────────────────────────────
# BASIC SERIALIZERS
# ─────────────────────────────────────────────────────────────────────────────

class MainCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = MainCategory
        fields = ['id', 'name', 'slug', 'icon', 'order']


class CategorySerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()
    main_category_name = serializers.CharField(source='main_category.name', read_only=True)
    main_category_slug = serializers.CharField(source='main_category.slug', read_only=True)
    product_count = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = [
            'id', 'name', 'slug', 'image', 'description',
            'is_featured', 'order',
            'main_category_name', 'main_category_slug',
            'product_count'
        ]

    def get_image(self, obj):
        if obj.image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
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
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        return None


class BrandSerializer(serializers.ModelSerializer):
    class Meta:
        model = Brand
        fields = ['id', 'name', 'slug']


# ─────────────────────────────────────────────────────────────────────────────
# PRODUCT IMAGE & VARIANT
# ─────────────────────────────────────────────────────────────────────────────

class ProductImageSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()

    class Meta:
        model = ProductImage
        fields = ['id', 'image', 'alt_text', 'is_primary', 'order', 'variant']

    def get_image(self, obj):
        if obj.image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        return None


class ProductVariantSerializer(serializers.ModelSerializer):
    final_price = serializers.ReadOnlyField()
    final_original_price = serializers.ReadOnlyField()
    in_stock = serializers.ReadOnlyField()
    size_display = serializers.CharField(source='get_size_display', read_only=True)

    class Meta:
        model = ProductVariant
        fields = [
            'id', 'size', 'size_display', 'color', 'color_hex',
            'stock', 'price_override', 'final_price',
            'final_original_price', 'in_stock', 'sku_suffix'
        ]


# ─────────────────────────────────────────────────────────────────────────────
# REVIEW
# ─────────────────────────────────────────────────────────────────────────────

class ReviewSerializer(serializers.ModelSerializer):
    date = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField()
    # user_name is read_only — set from request.user in view
    user_name = serializers.CharField(read_only=True)

    class Meta:
        model = Review
        fields = [
            'id', 'user_name', 'rating', 'title', 'comment',
            'image', 'variant_info', 'is_verified_purchase',
            'is_featured', 'date'
        ]

    def get_date(self, obj):
        from django.utils.timesince import timesince
        return f"{timesince(obj.created_at).split(',')[0]} ago"

    def get_image(self, obj):
        if obj.image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        return None


# ─────────────────────────────────────────────────────────────────────────────
# PRODUCT — LIST (lightweight, for grids/carousels)
# ─────────────────────────────────────────────────────────────────────────────

class ProductListSerializer(serializers.ModelSerializer):
    images = ProductImageSerializer(many=True, read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    category_slug = serializers.CharField(source='category.slug', read_only=True)
    main_category_name = serializers.CharField(
        source='category.main_category.name', read_only=True
    )
    main_category_slug = serializers.CharField(
        source='category.main_category.slug', read_only=True
    )
    brand_name = serializers.SerializerMethodField()
    space_tags = SpaceTagSerializer(many=True, read_only=True)
    review_count = serializers.SerializerMethodField()
    average_rating = serializers.SerializerMethodField()
    discount_percentage = serializers.SerializerMethodField()

    # Available sizes and colors (for filter badges)
    available_sizes = serializers.SerializerMethodField()
    available_colors = serializers.SerializerMethodField()
    in_stock = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            'id', 'name', 'slug', 'sku',
            'category_name', 'category_slug',
            'main_category_name', 'main_category_slug',
            'brand_name',
            'price', 'original_price', 'discount_percentage',
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
            disc = ((obj.original_price - obj.price) / obj.original_price) * 100
            return round(disc)
        return 0

    def get_available_sizes(self, obj):
        return list(
            obj.variants.values_list('size', flat=True).distinct()
        )

    def get_available_colors(self, obj):
        colors = obj.variants.exclude(color='').values('color', 'color_hex').distinct()
        return list(colors)

    def get_in_stock(self, obj):
        return obj.variants.filter(stock__gt=0).exists()


# ─────────────────────────────────────────────────────────────────────────────
# PRODUCT — DETAIL (full data for product detail page)
# ─────────────────────────────────────────────────────────────────────────────

class ProductDetailSerializer(ProductListSerializer):
    variants = ProductVariantSerializer(many=True, read_only=True)
    reviews = ReviewSerializer(many=True, read_only=True)
    highlights_list = serializers.SerializerMethodField()
    care_instructions_list = serializers.SerializerMethodField()
    what_you_get_list = serializers.SerializerMethodField()

    class Meta(ProductListSerializer.Meta):
        fields = ProductListSerializer.Meta.fields + [
            'description', 'highlights_list',
            'care_level', 'sunlight', 'watering',
            'pet_friendly', 'air_purifying',
            'care_instructions_list', 'what_you_get_list',
            'warranty_info', 'return_policy',
            'variants', 'reviews',
        ]

    def get_highlights_list(self, obj):
        if not obj.highlights:
            return []
        return [h.strip() for h in obj.highlights.split('\n') if h.strip()]

    def get_care_instructions_list(self, obj):
        if not obj.care_instructions:
            return []
        return [c.strip() for c in obj.care_instructions.split('\n') if c.strip()]

    def get_what_you_get_list(self, obj):
        if not obj.what_you_get:
            return []
        return [w.strip() for w in obj.what_you_get.split('\n') if w.strip()]


# ─────────────────────────────────────────────────────────────────────────────
# PRODUCT — SEARCH (ultra-lightweight for search dropdown)
# ─────────────────────────────────────────────────────────────────────────────

class ProductSearchSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()
    category_name = serializers.CharField(source='category.name', read_only=True)
    main_category_slug = serializers.CharField(
        source='category.main_category.slug', read_only=True
    )
    discount_percentage = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            'id', 'name', 'slug', 'sku', 'price', 'original_price',
            'image', 'category_name', 'main_category_slug', 'discount_percentage'
        ]

    def get_image(self, obj):
        primary = obj.images.filter(is_primary=True).first() or obj.images.first()
        if primary:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(primary.image.url)
            return primary.image.url
        return None

    def get_discount_percentage(self, obj):
        if obj.original_price and obj.original_price > obj.price:
            disc = ((obj.original_price - obj.price) / obj.original_price) * 100
            return round(disc)
        return 0


# ─────────────────────────────────────────────────────────────────────────────
# WATCH & SHOP
# ─────────────────────────────────────────────────────────────────────────────

class WatchAndShopSerializer(serializers.ModelSerializer):
    thumbnail = serializers.SerializerMethodField()
    product_slug = serializers.CharField(source='product.slug', read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True)

    class Meta:
        model = WatchAndShop
        fields = [
            'id', 'title', 'video_url', 'thumbnail',
            'product_slug', 'product_name', 'order'
        ]

    def get_thumbnail(self, obj):
        if obj.thumbnail:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.thumbnail.url)
            return obj.thumbnail.url
        return None


# ─────────────────────────────────────────────────────────────────────────────
# SITE CONFIG & COUPON
# ─────────────────────────────────────────────────────────────────────────────

class SiteConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = SiteConfig
        fields = '__all__'


class CouponSerializer(serializers.ModelSerializer):
    class Meta:
        model = Coupon
        fields = ['code', 'discount_type', 'value', 'min_order_value']


# ─────────────────────────────────────────────────────────────────────────────
# HOME DATA (aggregated response for homepage)
# ─────────────────────────────────────────────────────────────────────────────

class NavbarDataSerializer(serializers.ModelSerializer):
    """Used to build the dynamic navbar menu"""
    categories = CategorySerializer(many=True, read_only=True)

    class Meta:
        model = MainCategory
        fields = ['id', 'name', 'slug', 'icon', 'order', 'categories']