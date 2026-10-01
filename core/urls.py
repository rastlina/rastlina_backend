from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from .sitemaps import sitemap

urlpatterns = [
    path('sitemap.xml', sitemap, name='sitemap'),
    path('admin/', admin.site.urls),

    # Auth endpoints
    path('api/auth/', include('accounts.urls')),
    path('accounts/', include('allauth.urls')),  # Required by allauth internally

    # Store (products, categories, etc.)
    path('api/store/', include('store.urls')),

    # Orders
    path('api/orders/', include('orders.urls')),

    # Payments
    path('api/payments/', include('payments.urls')),

    #  Dynamic page content
    path('api/content/', include('content.urls')),

    # Mail forms (bulk order, contact, complaint)
    path('api/forms/', include('mails.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
