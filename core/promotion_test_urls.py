from django.urls import include, path
urlpatterns = [path('api/store/', include('store.urls')), path('api/orders/', include('orders.urls'))]
