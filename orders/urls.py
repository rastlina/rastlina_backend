"""orders/urls.py"""

from django.urls import path
from .views import (
    CheckoutView,
    OrderListView,
    order_detail,
    CancelOrderView,
    ReturnRequestCreateView,
    OrderReturnRequestCreateView,
    ValidateExchangeCodeView,
    GuestOrderTrackView,
)
from .shiprocket_views import check_pincode_serviceability, track_shipment_view

urlpatterns = [
    path('checkout/', CheckoutView.as_view(), name='checkout'),
    path('', OrderListView.as_view(), name='order-list'),
    path('<int:pk>/', order_detail, name='order-detail'),
    path('<int:pk>/cancel/', CancelOrderView.as_view(), name='cancel-order'),
    path('<int:order_id>/exchange/', ReturnRequestCreateView.as_view(), name='exchange-request'),
    path('<int:order_id>/return-product/', OrderReturnRequestCreateView.as_view(), name='return-product'),
    path('validate-exchange-code/', ValidateExchangeCodeView.as_view(), name='validate-exchange'),
    path('track/', GuestOrderTrackView.as_view(), name='guest-track'),
    # Shiprocket
    path('check-serviceability/', check_pincode_serviceability, name='check-serviceability'),
    path('<int:pk>/track-shipment/', track_shipment_view, name='track-shipment'),
]
