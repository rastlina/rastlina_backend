"""orders/urls.py"""

from django.urls import path
from .views import (
    CheckoutView,
    OrderListView,
    order_detail,
    CancelOrderView,
    ReturnRequestCreateView,
    ValidateExchangeCodeView,
    GuestOrderTrackView,
)

urlpatterns = [
    # Checkout — guest + authenticated
    path('checkout/', CheckoutView.as_view(), name='checkout'),

    # Authenticated order list / detail
    path('', OrderListView.as_view(), name='order-list'),
    path('<int:pk>/', order_detail, name='order-detail'),
    path('<int:pk>/cancel/', CancelOrderView.as_view(), name='cancel-order'),
    path('<int:order_id>/return/', ReturnRequestCreateView.as_view(), name='return-request'),

    # Exchange code validation
    path('validate-exchange-code/', ValidateExchangeCodeView.as_view(), name='validate-exchange'),

    # Guest tracking (no auth)
    path('track/', GuestOrderTrackView.as_view(), name='guest-track'),
]