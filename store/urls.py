from django.urls import path
from .views import (
    NavbarDataView, MainCategoryListView, CategoryListView,
    SpaceTagListView, BrandListView,
    SizeOptionListView, ColorOptionListView,
    ProductListView, ProductDetailView, RelatedProductsView,
    ReviewListCreateView,
    FAQListView, HomeDataView, GlobalSearchView,
    ValidateCouponView, SiteConfigView, ProductFilterOptionsView,WatchAndShopListView, WatchAndShopDetailView,ActiveCouponsView
)

urlpatterns = [
    path('navbar/', NavbarDataView.as_view(), name='navbar-data'),
    path('main-categories/', MainCategoryListView.as_view(), name='main-category-list'),
    path('categories/', CategoryListView.as_view(), name='category-list'),
    path('spaces/', SpaceTagListView.as_view(), name='space-list'),
    path('brands/', BrandListView.as_view(), name='brand-list'),
    path('sizes/', SizeOptionListView.as_view(), name='size-list'),
    path('colors/', ColorOptionListView.as_view(), name='color-list'),
    path('products/', ProductListView.as_view(), name='product-list'),
    path('products/<slug:slug>/', ProductDetailView.as_view(), name='product-detail'),
    path('products/<slug:slug>/reviews/', ReviewListCreateView.as_view(), name='product-reviews'),
    path('products/<slug:slug>/related/', RelatedProductsView.as_view(), name='product-related'),
    path('faqs/', FAQListView.as_view(), name='faq-list'),
    path('home-data/', HomeDataView.as_view(), name='home-data'),
    path('search/', GlobalSearchView.as_view(), name='search'),
    path('filter-options/', ProductFilterOptionsView.as_view(), name='filter-options'),
    path('config/', SiteConfigView.as_view(), name='site-config'),
    path('validate-coupon/', ValidateCouponView.as_view(), name='validate-coupon'),
    path('watch-and-shop/', WatchAndShopListView.as_view(), name='watch-and-shop-list'),
    path('watch-and-shop/<slug:slug>/', WatchAndShopDetailView.as_view(), name='watch-and-shop-detail'),
    path('active-coupons/', ActiveCouponsView.as_view(), name='active-coupons'),
]