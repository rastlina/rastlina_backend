"""
payments/views.py
Rastlina — Payment views.
  POST /api/payments/verify/   — client callback after Razorpay modal
  POST /api/payments/webhook/  — Razorpay server-to-server webhook
Both guest and authenticated orders are handled identically here; auth is
on the order itself, not on these endpoints.
"""

import json
import logging

from django.db import transaction
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import permissions, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .razorpay_client import verify_webhook_signature
from .serializers import PaymentVerifySerializer
from .services import (
    capture_payment_from_client,
    capture_payment_from_webhook,
    mark_payment_failed_from_webhook,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/payments/verify/
# ─────────────────────────────────────────────────────────────────────────────

class VerifyPaymentView(APIView):
    """
    Called by the frontend immediately after the Razorpay modal closes with
    a successful payment. Works for both guest and authenticated checkouts
    because we look up the order by razorpay_order_id (not by user).

    Allow any — the order itself is the auth token here.
    Guest users must supply the same razorpay_order_id they received at
    checkout; they cannot enumerate other orders this way.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PaymentVerifySerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        result = capture_payment_from_client(
            razorpay_order_id=data['razorpay_order_id'],
            razorpay_payment_id=data['razorpay_payment_id'],
            razorpay_signature=data['razorpay_signature'],
        )

        if result['success']:
            return Response(
                {
                    'message': result.get('message', 'Payment verified successfully'),
                    'order_id': result.get('order_id'),
                },
                status=status.HTTP_200_OK,
            )
        return Response(
            {'error': result.get('error', 'Verification failed')},
            status=status.HTTP_400_BAD_REQUEST,
        )


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/payments/webhook/   (CSRF exempt — server-to-server)
# ─────────────────────────────────────────────────────────────────────────────

@method_decorator(csrf_exempt, name='dispatch')
class RazorpayWebhookView(APIView):
    """
    Razorpay sends signed POST events here.
    We verify the signature first; if invalid we return 400 immediately.

    Supported events:
      payment.captured  — mark order Paid + Confirmed, deduct stock
      payment.failed    — mark order Failed
      refund.created    — informational log only (refund initiated via API)

    All other events are logged and acknowledged.
    """
    permission_classes = [AllowAny]
    authentication_classes = []  # No DRF auth — Razorpay signs its own requests

    def post(self, request):
        webhook_signature = request.headers.get('X-Razorpay-Signature', '')

        # ── 1. Verify webhook signature ───────────────────────────────────────
        try:
            verify_webhook_signature(
                body=request.body.decode('utf-8'),
                signature=webhook_signature,
            )
        except RuntimeError as config_err:
            logger.error("Webhook config error: %s", config_err)
            return Response({'error': 'Webhook not configured'}, status=500)
        except Exception as sig_err:
            logger.warning("Webhook signature invalid: %s", sig_err)
            return Response({'error': 'Invalid signature'}, status=400)

        # ── 2. Parse body ─────────────────────────────────────────────────────
        try:
            payload = json.loads(request.body)
        except json.JSONDecodeError:
            return Response({'error': 'Invalid JSON'}, status=400)

        event = payload.get('event', '')
        logger.info("Razorpay webhook event: %s", event)

        # ── 3. Route event ────────────────────────────────────────────────────
        payment_entity = (
            payload.get('payload', {})
            .get('payment', {})
            .get('entity', {})
        )
        rzp_order_id = payment_entity.get('order_id', '')
        rzp_payment_id = payment_entity.get('id', '')
        amount_paise = payment_entity.get('amount', 0)

        if event == 'payment.captured':
            with transaction.atomic():
                capture_payment_from_webhook(
                    rzp_order_id=rzp_order_id,
                    rzp_payment_id=rzp_payment_id,
                    amount_paise=amount_paise,
                    raw_payload=payload,
                )

        elif event == 'payment.failed':
            error_entity = (
                payload.get('payload', {})
                .get('payment', {})
                .get('entity', {})
            )
            mark_payment_failed_from_webhook(
                rzp_order_id=rzp_order_id,
                rzp_payment_id=rzp_payment_id,
                raw_payload=payload,
            )

        # refund.created, order.paid, etc. — acknowledge without action
        # (refunds are initiated by us via the API, not via webhook)

        return Response({'status': 'handled'}, status=200)