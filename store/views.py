from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticatedOrReadOnly
from rest_framework.parsers import MultiPartParser, FormParser
from django.db.models import Q, Avg
from decimal import Decimal
from django.db import models
from .models import Coupon
from .serializers import CouponSerializer
from rest_framework.generics import ListAPIView
from django.utils import timezone

from .models import (
    MainCategory, HeroSlide, Category, SpaceTag, Brand,
    SizeOption, ColorOption,
    Product, ProductVariant, ProductImage, DeliveryEstimate,
    Review, FAQ, WatchAndShop, SiteConfig, Coupon,
)
from .serializers import (
    MainCategorySerializer, HeroSlideSerializer, CategorySerializer,
    SpaceTagSerializer, BrandSerializer,
    SizeOptionSerializer, ColorOptionSerializer,
    ProductListSerializer, ProductDetailSerializer, ProductSearchSerializer,
    ReviewSerializer, FAQSerializer,
    WatchAndShopSerializer, SiteConfigSerializer, NavbarDataSerializer,
)


# ─────────────────────────────────────────────────────────────────────────────
# NAVBAR
# ─────────────────────────────────────────────────────────────────────────────

class NavbarDataView(APIView):
    """GET /api/store/navbar/ — Full dynamic navbar + hero slides + sizes"""
    permission_classes = [AllowAny]

    def get(self, request):
        ctx = {'request': request}
        main_cats = MainCategory.objects.filter(is_active=True).prefetch_related('categories')
        hero_slides = HeroSlide.objects.filter(is_active=True)
        spaces = SpaceTag.objects.filter(is_featured=True)
        # Sizes that should appear in the navbar "Shop by Size"
                # Dynamic sizes per main category
        plants_sizes = SizeOption.objects.filter(
            show_in_navbar=True,
            variants__product__category__main_category__slug='plants'
        ).distinct()

        planters_sizes = SizeOption.objects.filter(
            show_in_navbar=True,
            variants__product__category__main_category__slug='planters'
        ).distinct()

        seeds_sizes = SizeOption.objects.filter(
            show_in_navbar=True,
            variants__product__category__main_category__slug='seeds'
        ).distinct()

        return Response({
            'main_categories': NavbarDataSerializer(main_cats, many=True, context=ctx).data,
            'hero_slides': HeroSlideSerializer(hero_slides, many=True, context=ctx).data,
            'featured_spaces': SpaceTagSerializer(spaces, many=True, context=ctx).data,

            'plants_sizes': SizeOptionSerializer(plants_sizes, many=True).data,
            'planters_sizes': SizeOptionSerializer(planters_sizes, many=True).data,
            'seeds_sizes': SizeOptionSerializer(seeds_sizes, many=True).data,
        })


# ─────────────────────────────────────────────────────────────────────────────
# BASIC LIST VIEWS
# ─────────────────────────────────────────────────────────────────────────────

class MainCategoryListView(generics.ListAPIView):
    serializer_class = MainCategorySerializer
    queryset = MainCategory.objects.filter(is_active=True)
    permission_classes = [AllowAny]


class CategoryListView(generics.ListAPIView):
    serializer_class = CategorySerializer
    permission_classes = [AllowAny]

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx['request'] = self.request
        return ctx

    def get_queryset(self):
        qs = Category.objects.select_related('main_category').all()
        main_cat = self.request.query_params.get('main_category')
        featured = self.request.query_params.get('featured')
        if main_cat:
            qs = qs.filter(main_category__slug=main_cat)
        if featured == 'true':
            qs = qs.filter(is_featured=True)
        return qs


class SpaceTagListView(generics.ListAPIView):
    serializer_class = SpaceTagSerializer
    permission_classes = [AllowAny]

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx['request'] = self.request
        return ctx

    def get_queryset(self):
        qs = SpaceTag.objects.all()
        if self.request.query_params.get('featured') == 'true':
            qs = qs.filter(is_featured=True)
        return qs


class BrandListView(generics.ListAPIView):
    serializer_class = BrandSerializer
    queryset = Brand.objects.all()
    permission_classes = [AllowAny]


class SizeOptionListView(generics.ListAPIView):
    """GET /api/store/sizes/ — All admin-managed size options"""
    serializer_class = SizeOptionSerializer
    queryset = SizeOption.objects.all()
    permission_classes = [AllowAny]


class ColorOptionListView(generics.ListAPIView):
    """GET /api/store/colors/ — All admin-managed color options"""
    serializer_class = ColorOptionSerializer
    queryset = ColorOption.objects.all()
    permission_classes = [AllowAny]


# ─────────────────────────────────────────────────────────────────────────────
# PRODUCT VIEWS
# ─────────────────────────────────────────────────────────────────────────────

class ProductListView(generics.ListAPIView):
    """
    GET /api/store/products/

    Query params:
      main_category=plants    category=succulents    space=living-room
      size=Small              color=Terracotta       care_level=easy
      pet_friendly=true       air_purifying=true
      min_price=100           max_price=1000
      is_new_arrival=true     is_best_seller=true
      is_trending=true        is_best_deal=true
      search=monstera         ordering=-price
    """
    serializer_class = ProductListSerializer
    permission_classes = [AllowAny]

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx['request'] = self.request
        return ctx

    def get_queryset(self):
        qs = Product.objects.filter(is_active=True).prefetch_related(
            'images', 'variants', 'variants__size', 'variants__color',
            'space_tags', 'reviews'
        ).select_related('category', 'category__main_category', 'brand')

        p = self.request.query_params

        if p.get('main_category'):
            qs = qs.filter(category__main_category__slug=p['main_category'])
        if p.get('category'):
            qs = qs.filter(category__slug=p['category'])
        if p.get('space'):
            qs = qs.filter(space_tags__slug=p['space'])

        # Size filter: match by size name (case-insensitive)
        if p.get('size'):
            qs = qs.filter(variants__size__name__iexact=p['size'])
        # Color filter: match by color name (case-insensitive)
        if p.get('color'):
            qs = qs.filter(variants__color__name__icontains=p['color'])

        if p.get('care_level'):
            qs = qs.filter(care_level=p['care_level'])
        if p.get('pet_friendly') == 'true':
            qs = qs.filter(pet_friendly=True)
        if p.get('air_purifying') == 'true':
            qs = qs.filter(air_purifying=True)
        if p.get('min_price'):
            qs = qs.filter(price__gte=p['min_price'])
        if p.get('max_price'):
            qs = qs.filter(price__lte=p['max_price'])
        if p.get('is_new_arrival') == 'true':
            qs = qs.filter(is_new_arrival=True)
        if p.get('is_best_seller') == 'true':
            qs = qs.filter(is_best_seller=True)
        if p.get('is_trending') == 'true':
            qs = qs.filter(is_trending=True)
        if p.get('is_best_deal') == 'true':
            qs = qs.filter(is_best_deal=True)

        search = p.get('search')
        if search:
            qs = qs.filter(
                Q(name__icontains=search) | Q(sku__icontains=search) |
                Q(description__icontains=search) | Q(category__name__icontains=search) |
                Q(brand__name__icontains=search)
            ).distinct()

        ordering = p.get('ordering', '-created_at')
        valid = ['price', '-price', '-created_at', 'created_at', 'name', '-name']
        qs = qs.order_by(ordering if ordering in valid else '-created_at')
        return qs.distinct().order_by(ordering if ordering in valid else '-created_at')


class ProductDetailView(generics.RetrieveAPIView):
    """GET /api/store/products/<slug>/"""
    queryset = Product.objects.filter(is_active=True).prefetch_related(
        'images', 'images__color',
        'variants', 'variants__size', 'variants__color',
        'space_tags', 'reviews', 'delivery_estimates',
    ).select_related('category', 'category__main_category', 'brand')
    serializer_class = ProductDetailSerializer
    lookup_field = 'slug'
    permission_classes = [AllowAny]

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx['request'] = self.request
        return ctx


class RelatedProductsView(APIView):
    """
    GET /api/store/products/<slug>/related/
    Returns up to 8 products in the same category (excluding current product).
    Falls back to same main_category if category has < 4 products.
    """
    permission_classes = [AllowAny]

    def get(self, request, slug):
        try:
            product = Product.objects.select_related(
                'category', 'category__main_category'
            ).get(slug=slug, is_active=True)
        except Product.DoesNotExist:
            return Response({'results': []})

        ctx = {'request': request}
        base_qs = Product.objects.filter(is_active=True).exclude(slug=slug).prefetch_related(
            'images', 'variants', 'variants__size', 'variants__color', 'space_tags', 'reviews'
        ).select_related('category', 'category__main_category', 'brand')

        # Same category first
        related = list(base_qs.filter(category=product.category)[:8])

        # If not enough, fill with same main category
        if len(related) < 4:
            exclude_ids = [p.id for p in related] + [product.id]
            fill = base_qs.filter(
                category__main_category=product.category.main_category
            ).exclude(id__in=exclude_ids)[:8 - len(related)]
            related += list(fill)

        return Response({
            'results': ProductListSerializer(related, many=True, context=ctx).data
        })


# ─────────────────────────────────────────────────────────────────────────────
# REVIEWS
# ─────────────────────────────────────────────────────────────────────────────

class ReviewListCreateView(generics.ListCreateAPIView):
    """GET+POST /api/store/products/<slug>/reviews/"""
    serializer_class = ReviewSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    parser_classes = [MultiPartParser, FormParser]

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx['request'] = self.request
        return ctx

    def get_queryset(self):
        return Review.objects.filter(
            product__slug=self.kwargs['slug']
        ).order_by('-created_at')

    def perform_create(self, serializer):
        product = Product.objects.get(slug=self.kwargs['slug'])
        user = self.request.user
        user_name = "Anonymous"
        if user.is_authenticated:
            user_name = f"{user.first_name} {user.last_name}".strip() or user.email.split('@')[0]
        serializer.save(
            product=product,
            user=user if user.is_authenticated else None,
            user_name=user_name,
            variant_info=self.request.data.get('variant_info', ''),
        )


# ─────────────────────────────────────────────────────────────────────────────
# FAQs
# ─────────────────────────────────────────────────────────────────────────────

class FAQListView(generics.ListAPIView):
    """GET /api/store/faqs/ — Global FAQs for product pages"""
    serializer_class = FAQSerializer
    queryset = FAQ.objects.filter(is_active=True)
    permission_classes = [AllowAny]


# ─────────────────────────────────────────────────────────────────────────────
# HOME DATA
# ─────────────────────────────────────────────────────────────────────────────

class HomeDataView(APIView):
    """GET /api/store/home-data/ — All homepage sections in one request"""
    permission_classes = [AllowAny]

    def get(self, request):
        ctx = {'request': request}

        def get_products(filters, limit=12):
            return ProductListSerializer(
                Product.objects.filter(is_active=True, **filters)
                .prefetch_related(
                    'images', 'variants', 'variants__size', 'variants__color', 'space_tags'
                )
                .select_related('category', 'category__main_category', 'brand')[:limit],
                many=True, context=ctx
            ).data

        return Response({
            'new_arrivals': get_products({'is_new_arrival': True}),
            'best_sellers': get_products({'is_best_seller': True}),
            'trending': get_products({'is_trending': True}),
            'best_deals': get_products({'is_best_deal': True}),
            'featured_categories': CategorySerializer(
                Category.objects.filter(is_featured=True).select_related('main_category'),
                many=True, context=ctx
            ).data,
            'featured_spaces': SpaceTagSerializer(
                SpaceTag.objects.filter(is_featured=True), many=True, context=ctx
            ).data,
            'watch_and_shop': WatchAndShopSerializer(
                WatchAndShop.objects.filter(is_active=True)[:4], many=True, context=ctx
            ).data,
            'all_planters': get_products({'category__main_category__slug': 'planters'}, limit=8),
            'all_seeds': get_products({'category__main_category__slug': 'seeds'}, limit=8),
            'all_care': get_products({'category__main_category__slug': 'care'}, limit=8),
            'hero_slides': HeroSlideSerializer(
                HeroSlide.objects.filter(is_active=True), many=True, context=ctx
            ).data,
            'featured_reviews': ReviewSerializer(
                Review.objects.filter(is_featured=True).select_related('product')[:6],
                many=True, context=ctx
            ).data,
        })


# ─────────────────────────────────────────────────────────────────────────────
# GLOBAL SEARCH
# ─────────────────────────────────────────────────────────────────────────────

class GlobalSearchView(APIView):
    """GET /api/store/search/?q=monstera"""
    permission_classes = [AllowAny]

    def get(self, request):
        q = request.query_params.get('q', '').strip()
        if len(q) < 1:
            return Response({'products': [], 'categories': [], 'message': 'Enter search term'})

        products = Product.objects.filter(
            Q(name__icontains=q) | Q(sku__icontains=q) |
            Q(category__name__icontains=q) | Q(brand__name__icontains=q) |
            Q(description__icontains=q),
            is_active=True
        ).select_related('category', 'brand').prefetch_related('images')[:8]

        return Response({
            'products': ProductSearchSerializer(
                products, many=True, context={'request': request}
            ).data,
            'categories': CategorySerializer(
                Category.objects.filter(name__icontains=q)[:5],
                many=True, context={'request': request}
            ).data,
            'spaces': SpaceTagSerializer(
                SpaceTag.objects.filter(name__icontains=q)[:4],
                many=True, context={'request': request}
            ).data,
            'term': q,
        })


# ─────────────────────────────────────────────────────────────────────────────
# FILTER OPTIONS (dynamic filters for shop page)
# ─────────────────────────────────────────────────────────────────────────────

class ProductFilterOptionsView(APIView):
    """
    GET /api/store/filter-options/
    Returns all available filter values for the current product set.
    Frontend uses this to build the dynamic filter sidebar.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        qs = Product.objects.filter(is_active=True).prefetch_related(
            'variants', 'variants__size', 'variants__color', 'space_tags'
        ).select_related('category', 'category__main_category')

        p = request.query_params
        if p.get('main_category'):
            qs = qs.filter(category__main_category__slug=p['main_category'])
        if p.get('category'):
            qs = qs.filter(category__slug=p['category'])
        if p.get('space'):
            qs = qs.filter(space_tags__slug=p['space'])

        prices = list(qs.values_list('price', flat=True))

        # Sizes: from SizeOption FK
        size_ids = ProductVariant.objects.filter(
            product__in=qs
        ).values_list('size_id', flat=True).distinct()
        sizes = SizeOptionSerializer(
            SizeOption.objects.filter(id__in=size_ids), many=True
        ).data

        # Colors: from ColorOption FK
        color_ids = ProductVariant.objects.filter(
            product__in=qs, color__isnull=False
        ).values_list('color_id', flat=True).distinct()
        colors = ColorOptionSerializer(
            ColorOption.objects.filter(id__in=color_ids), many=True
        ).data

        care_levels = list(
            qs.exclude(care_level='').values_list('care_level', flat=True).distinct()
        )

        spaces = SpaceTagSerializer(
            SpaceTag.objects.filter(products__in=qs).distinct(),
            many=True, context={'request': request}
        ).data

        categories = CategorySerializer(
            Category.objects.filter(
                products__in=qs
            ).distinct().select_related('main_category'),
            many=True, context={'request': request}
        ).data

        return Response({
            'price_range': {
                'min': float(min(prices)) if prices else 0,
                'max': float(max(prices)) if prices else 0,
            },
            'sizes': sizes,
            'colors': colors,
            'care_levels': care_levels,
            'spaces': spaces,
            'categories': categories,
            'has_pet_friendly': qs.filter(pet_friendly=True).exists(),
            'has_air_purifying': qs.filter(air_purifying=True).exists(),
        })


# ─────────────────────────────────────────────────────────────────────────────
# COUPON VALIDATION
# ─────────────────────────────────────────────────────────────────────────────

class ValidateCouponView(APIView):
    """POST /api/store/validate-coupon/  Body: { code, order_total }"""
    permission_classes = [AllowAny]

    def post(self, request):
        code = request.data.get('code', '').strip().upper()
        order_total = Decimal(str(request.data.get('order_total', 0)))
        if not code:
            return Response({'error': 'Coupon code required'}, status=400)
        try:
            coupon = Coupon.objects.get(code=code, active=True)
            now = timezone.now()
            if coupon.valid_from > now or coupon.valid_to < now:
                return Response({'error': 'Coupon has expired'}, status=400)
            if coupon.uses_count >= coupon.usage_limit:
                return Response({'error': 'Coupon usage limit reached'}, status=400)
            if order_total < coupon.min_order_value:
                return Response(
                    {'error': f'Minimum order of ₹{coupon.min_order_value} required'},
                    status=400
                )
            discount = (
                (order_total * coupon.value / 100)
                if coupon.discount_type == 'percentage'
                else coupon.value
            )
            return Response({
                'success': True, 'code': coupon.code,
                'discount_type': coupon.discount_type,
                'discount': float(discount),
                'message': f'Coupon applied! You save ₹{discount:.0f}',
            })
        except Coupon.DoesNotExist:
            return Response({'error': 'Invalid coupon code'}, status=404)


# ─────────────────────────────────────────────────────────────────────────────
# SITE CONFIG
# ─────────────────────────────────────────────────────────────────────────────

class SiteConfigView(APIView):
    """GET /api/store/config/"""
    permission_classes = [AllowAny]

    def get(self, request):
        config = SiteConfig.objects.first()
        if not config:
            config = SiteConfig.objects.create()
        return Response(SiteConfigSerializer(config).data)

class WatchAndShopListView(generics.ListAPIView):
    permission_classes = [AllowAny]
    queryset = WatchAndShop.objects.filter(is_active=True).order_by('order')
    serializer_class = WatchAndShopSerializer

class WatchAndShopDetailView(generics.RetrieveAPIView):
    permission_classes = [AllowAny]
    queryset = WatchAndShop.objects.filter(is_active=True)
    serializer_class = WatchAndShopSerializer
    lookup_field = 'slug'

# ─────────────────────────────────────────────────────────────────────────────
# ACTIVE COUPONS
# ─────────────────────────────────────────────────────────────────────────────

class ActiveCouponsView(ListAPIView):
    serializer_class = CouponSerializer

    def get_queryset(self):
        now = timezone.now()

        return Coupon.objects.filter(
            active=True,
            valid_from__lte=now,
            valid_to__gte=now,
            uses_count__lt=models.F('usage_limit')
        ).order_by('min_order_value')