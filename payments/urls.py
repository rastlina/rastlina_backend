"""
payments/urls.py
Mount under /api/payments/ in your root urls.py:
    path('api/payments/', include('payments.urls')),
"""

from django.urls import path

from .views import RazorpayWebhookView, VerifyPaymentView

urlpatterns = [
    path('verify/', VerifyPaymentView.as_view(), name='payment-verify'),
    path('webhook/', RazorpayWebhookView.as_view(), name='razorpay-webhook'),
]