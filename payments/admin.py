"""
payments/admin.py
Rastlina — Payment admin.
PaymentLog is read-only in admin (append-only audit trail).
"""

from django.contrib import admin
from django.utils.html import format_html

from .models import PaymentLog


@admin.register(PaymentLog)
class PaymentLogAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'event', 'source', 'order_link', 'razorpay_payment_id',
        'amount_display', 'success_badge', 'created_at',
    ]
    list_filter = ['event', 'source', 'success', 'created_at']
    search_fields = [
        'razorpay_order_id', 'razorpay_payment_id',
        'razorpay_refund_id', 'order__id',
    ]
    readonly_fields = [f.name for f in PaymentLog._meta.get_fields() if hasattr(f, 'name')]
    list_per_page = 50
    ordering = ['-created_at']

    # Disable add / change / delete — this is a pure audit log
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser  # superuser can purge if needed

    # ── Custom columns ─────────────────────────────────────────────────────

    def order_link(self, obj):
        if obj.order_id:
            url = f'/admin/orders/order/{obj.order_id}/change/'
            return format_html('<a href="{}">Order #{}</a>', url, obj.order_id)
        return '—'
    order_link.short_description = 'Order'
    order_link.allow_tags = True

    def amount_display(self, obj):
        if obj.amount_paise:
            return f'₹{obj.amount_paise / 100:,.2f}'
        return '—'
    amount_display.short_description = 'Amount'

    def success_badge(self, obj):
        if obj.success:
            return format_html(
                '<span style="color:#16a34a;font-weight:bold;">✓ OK</span>'
            )
        return format_html(
            '<span style="color:#dc2626;font-weight:bold;">✗ FAIL</span>'
        )
    success_badge.short_description = 'Status'