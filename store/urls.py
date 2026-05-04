from django.urls import path
from .views import (
    NavbarDataView,
    MainCategoryListView, CategoryListView,
    SpaceTagListView, BrandListView,
    ProductListView, ProductDetailView,
    ReviewListCreateView,
    HomeDataView, GlobalSearchView,
    ValidateCouponView, SiteConfigView,
    ProductFilterOptionsView,
)

urlpatterns = [
    # Navigation
    path('navbar/', NavbarDataView.as_view(), name='navbar-data'),
    path('main-categories/', MainCategoryListView.as_view(), name='main-category-list'),
    path('categories/', CategoryListView.as_view(), name='category-list'),
    path('spaces/', SpaceTagListView.as_view(), name='space-list'),
    path('brands/', BrandListView.as_view(), name='brand-list'),

    # Products
    path('products/', ProductListView.as_view(), name='product-list'),
    path('products/<slug:slug>/', ProductDetailView.as_view(), name='product-detail'),
    path('products/<slug:slug>/reviews/', ReviewListCreateView.as_view(), name='product-reviews'),

    # Home + search
    path('home-data/', HomeDataView.as_view(), name='home-data'),
    path('search/', GlobalSearchView.as_view(), name='search'),

    # Filters
    path('filter-options/', ProductFilterOptionsView.as_view(), name='filter-options'),

    # Config
    path('config/', SiteConfigView.as_view(), name='site-config'),
    path('validate-coupon/', ValidateCouponView.as_view(), name='validate-coupon'),
]