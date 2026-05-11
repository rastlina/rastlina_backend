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

urlpatterns = [
    path('checkout/', CheckoutView.as_view(), name='checkout'),
    path('', OrderListView.as_view(), name='order-list'),
    path('<int:pk>/', order_detail, name='order-detail'),
    path('<int:pk>/cancel/', CancelOrderView.as_view(), name='cancel-order'),
    # Exchange request (reports defect → exchange code generated)
    path('<int:order_id>/exchange/', ReturnRequestCreateView.as_view(), name='exchange-request'),
    # Return request (physical return → admin handles refund)
    path('<int:order_id>/return-product/', OrderReturnRequestCreateView.as_view(), name='return-product'),
    # Exchange code validation
    path('validate-exchange-code/', ValidateExchangeCodeView.as_view(), name='validate-exchange'),
    # Guest tracking
    path('track/', GuestOrderTrackView.as_view(), name='guest-track'),
]