from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticatedOrReadOnly
from rest_framework.parsers import MultiPartParser, FormParser
from django.db.models import Q, Avg
from decimal import Decimal
from django.utils import timezone

from .models import (
    MainCategory, Category, SpaceTag, Brand,
    Product, ProductImage, Review,
    WatchAndShop, SiteConfig, Coupon,ProductVariant,
)
from .serializers import (
    MainCategorySerializer, CategorySerializer, SpaceTagSerializer,
    BrandSerializer, ProductListSerializer, ProductDetailSerializer,
    ProductSearchSerializer, ReviewSerializer,
    WatchAndShopSerializer, SiteConfigSerializer, NavbarDataSerializer
)


# ─────────────────────────────────────────────────────────────────────────────
# NAVBAR DATA — single endpoint to build the entire dynamic menu
# ─────────────────────────────────────────────────────────────────────────────

class NavbarDataView(APIView):
    """
    GET /api/store/navbar/
    Returns all main categories with their sub-categories.
    Used to build the full dynamic navbar.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        ctx = {'request': request}
        main_cats = MainCategory.objects.filter(is_active=True).prefetch_related('categories')
        return Response(NavbarDataSerializer(main_cats, many=True, context=ctx).data)


# ─────────────────────────────────────────────────────────────────────────────
# BASIC LIST VIEWS
# ─────────────────────────────────────────────────────────────────────────────

class MainCategoryListView(generics.ListAPIView):
    """GET /api/store/main-categories/"""
    serializer_class = MainCategorySerializer
    queryset = MainCategory.objects.filter(is_active=True)
    permission_classes = [AllowAny]


class CategoryListView(generics.ListAPIView):
    """GET /api/store/categories/?main_category=plants&featured=true"""
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
    """GET /api/store/spaces/?featured=true"""
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
    """GET /api/store/brands/"""
    serializer_class = BrandSerializer
    queryset = Brand.objects.all()
    permission_classes = [AllowAny]


# ─────────────────────────────────────────────────────────────────────────────
# PRODUCT VIEWS
# ─────────────────────────────────────────────────────────────────────────────

class ProductListView(generics.ListAPIView):
    """
    GET /api/store/products/
    
    Query params (all optional):
      main_category=plants     → Filter by top-level nav section
      category=succulents      → Filter by sub-category slug
      space=living-room        → Filter by space tag
      size=medium              → Filter by variant size
      color=terracotta         → Filter by variant color
      care_level=easy          → Filter by care level
      pet_friendly=true        → Filter pet-friendly plants
      air_purifying=true       → Filter air-purifying plants
      min_price=100            → Price range min
      max_price=1000           → Price range max
      is_new_arrival=true      → Homepage sections
      is_best_seller=true
      is_trending=true
      is_best_deal=true
      search=monstera          → Full text search
      ordering=-price          → Sort: price / -price / -created_at / name
    """
    serializer_class = ProductListSerializer
    permission_classes = [AllowAny]

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx['request'] = self.request
        return ctx

    def get_queryset(self):
        qs = Product.objects.filter(is_active=True).prefetch_related(
            'images', 'variants', 'space_tags', 'reviews'
        ).select_related('category', 'category__main_category', 'brand')

        params = self.request.query_params

        # ── Category filters ──────────────────────────────
        main_cat = params.get('main_category')
        category = params.get('category')
        if main_cat:
            qs = qs.filter(category__main_category__slug=main_cat)
        if category:
            qs = qs.filter(category__slug=category)

        # ── Space / usage filter ──────────────────────────
        space = params.get('space')
        if space:
            qs = qs.filter(space_tags__slug=space)

        # ── Variant filters (size / color) ────────────────
        size = params.get('size')
        color = params.get('color')
        if size:
            qs = qs.filter(variants__size=size)
        if color:
            qs = qs.filter(variants__color__icontains=color)

        # ── Plant attribute filters ───────────────────────
        care_level = params.get('care_level')
        pet_friendly = params.get('pet_friendly')
        air_purifying = params.get('air_purifying')
        if care_level:
            qs = qs.filter(care_level=care_level)
        if pet_friendly == 'true':
            qs = qs.filter(pet_friendly=True)
        if air_purifying == 'true':
            qs = qs.filter(air_purifying=True)

        # ── Price range ───────────────────────────────────
        min_price = params.get('min_price')
        max_price = params.get('max_price')
        if min_price:
            qs = qs.filter(price__gte=min_price)
        if max_price:
            qs = qs.filter(price__lte=max_price)

        # ── Homepage section flags ────────────────────────
        if params.get('is_new_arrival') == 'true':
            qs = qs.filter(is_new_arrival=True)
        if params.get('is_best_seller') == 'true':
            qs = qs.filter(is_best_seller=True)
        if params.get('is_trending') == 'true':
            qs = qs.filter(is_trending=True)
        if params.get('is_best_deal') == 'true':
            qs = qs.filter(is_best_deal=True)

        # ── Full text search ──────────────────────────────
        search = params.get('search')
        if search:
            qs = qs.filter(
                Q(name__icontains=search) |
                Q(sku__icontains=search) |
                Q(description__icontains=search) |
                Q(category__name__icontains=search) |
                Q(brand__name__icontains=search)
            ).distinct()

        # ── Ordering ──────────────────────────────────────
        ordering = params.get('ordering', '-created_at')
        valid_orderings = ['price', '-price', '-created_at', 'created_at', 'name', '-name']
        if ordering in valid_orderings:
            qs = qs.order_by(ordering)
        else:
            qs = qs.order_by('-created_at')

        return qs.distinct()


class ProductDetailView(generics.RetrieveAPIView):
    """GET /api/store/products/<slug>/"""
    queryset = Product.objects.filter(is_active=True).prefetch_related(
        'images', 'variants', 'variants__images',
        'space_tags', 'reviews'
    ).select_related('category', 'category__main_category', 'brand')
    serializer_class = ProductDetailSerializer
    lookup_field = 'slug'
    permission_classes = [AllowAny]

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx['request'] = self.request
        return ctx


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

        variant_info = self.request.data.get('variant_info', '')
        serializer.save(
            product=product,
            user=user if user.is_authenticated else None,
            user_name=user_name,
            variant_info=variant_info
        )


# ─────────────────────────────────────────────────────────────────────────────
# HOME DATA
# ─────────────────────────────────────────────────────────────────────────────

class HomeDataView(APIView):
    """
    GET /api/store/home-data/
    Returns all sections needed for the homepage in one request.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        ctx = {'request': request}

        def get_products(filter_kwargs, limit=12):
            return ProductListSerializer(
                Product.objects.filter(
                    is_active=True, **filter_kwargs
                ).prefetch_related('images', 'variants', 'space_tags').select_related(
                    'category', 'category__main_category', 'brand'
                )[:limit],
                many=True, context=ctx
            ).data

        return Response({
            'new_arrivals': get_products({'is_new_arrival': True}),
            'best_sellers': get_products({'is_best_seller': True}),
            'trending': get_products({'is_trending': True}),
            'best_deals': get_products({'is_best_deal': True}),

            # "Explore by Category" — featured categories
            'featured_categories': CategorySerializer(
                Category.objects.filter(is_featured=True).select_related('main_category'),
                many=True, context=ctx
            ).data,

            # "Curate your atmosphere" — featured spaces
            'featured_spaces': SpaceTagSerializer(
                SpaceTag.objects.filter(is_featured=True),
                many=True, context=ctx
            ).data,

            # "Watch and Shop" videos
            'watch_and_shop': WatchAndShopSerializer(
                WatchAndShop.objects.filter(is_active=True)[:4],
                many=True, context=ctx
            ).data,

            # "Complete your garden" sections
            'all_planters': get_products(
                {'category__main_category__slug': 'planters'}, limit=8
            ),
            'all_seeds': get_products(
                {'category__main_category__slug': 'seeds'}, limit=8
            ),
            'all_care': get_products(
                {'category__main_category__slug': 'care'}, limit=8
            ),
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

        search_query = (
            Q(name__icontains=q) |
            Q(sku__icontains=q) |
            Q(category__name__icontains=q) |
            Q(brand__name__icontains=q) |
            Q(description__icontains=q)
        )

        products = Product.objects.filter(
            search_query, is_active=True
        ).select_related('category', 'brand').prefetch_related('images')[:8]

        categories = Category.objects.filter(name__icontains=q)[:5]
        spaces = SpaceTag.objects.filter(name__icontains=q)[:4]

        return Response({
            'products': ProductSearchSerializer(
                products, many=True, context={'request': request}
            ).data,
            'categories': CategorySerializer(
                categories, many=True, context={'request': request}
            ).data,
            'spaces': SpaceTagSerializer(
                spaces, many=True, context={'request': request}
            ).data,
            'term': q
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
                'success': True,
                'code': coupon.code,
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


# ─────────────────────────────────────────────────────────────────────────────
# FILTER OPTIONS (dynamic filters for products page)
# ─────────────────────────────────────────────────────────────────────────────

class ProductFilterOptionsView(APIView):
    """
    GET /api/store/filter-options/?main_category=plants&category=succulents
    
    Returns all available filter options for the current product set.
    Frontend uses this to build dynamic filter sidebar.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        qs = Product.objects.filter(is_active=True).prefetch_related(
            'variants', 'space_tags'
        ).select_related('category', 'category__main_category')

        # Apply category/space filters to scope the options
        main_cat = request.query_params.get('main_category')
        category = request.query_params.get('category')
        if main_cat:
            qs = qs.filter(category__main_category__slug=main_cat)
        if category:
            qs = qs.filter(category__slug=category)

        # Extract all available filter values from this product set
        prices = list(qs.values_list('price', flat=True))

        sizes = list(
            ProductVariant.objects.filter(product__in=qs)
            .values_list('size', flat=True)
            .distinct()
        )
        colors = list(
            ProductVariant.objects.filter(product__in=qs)
            .exclude(color='')
            .values('color', 'color_hex')
            .distinct()
        )
        care_levels = list(
            qs.exclude(care_level='')
            .values_list('care_level', flat=True)
            .distinct()
        )
        spaces = SpaceTagSerializer(
            SpaceTag.objects.filter(products__in=qs).distinct(),
            many=True,
            context={'request': request}
        ).data

        return Response({
            'price_range': {
                'min': min(prices) if prices else 0,
                'max': max(prices) if prices else 0,
            },
            'sizes': sizes,
            'colors': colors,
            'care_levels': care_levels,
            'spaces': spaces,
            'has_pet_friendly': qs.filter(pet_friendly=True).exists(),
            'has_air_purifying': qs.filter(air_purifying=True).exists(),
        })

   