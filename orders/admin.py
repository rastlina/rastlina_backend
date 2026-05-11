"""orders/admin.py"""

import csv

from django.contrib import admin
from django.http import HttpResponse
from django.utils import timezone
from django.utils.html import format_html

from .models import ExchangeCode, Order, OrderItem, OrderReturnRequest, ReturnRequest


def export_to_csv(modeladmin, request, queryset):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename=orders.csv'
    writer = csv.writer(response)
    writer.writerow([
        'Order ID', 'Name', 'Phone', 'Total',
        'Payment Status', 'Order Status',
        'Address', 'City', 'State', 'Date',
    ])
    for o in queryset:
        writer.writerow([
            o.id, f'{o.first_name} {o.last_name}'.strip(), o.phone,
            o.total_amount, o.payment_status, o.order_status,
            o.shipping_address, o.city, o.state,
            timezone.localtime(o.created_at).strftime('%d-%m-%Y %H:%M'),
        ])
    return response

export_to_csv.short_description = 'Export selected orders to CSV'


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ['product_name', 'variant_label', 'price', 'quantity', 'image_preview']

    def image_preview(self, obj):
        if obj.image_url:
            return format_html('<img src="{}" style="width:50px;height:auto;" />', obj.image_url)
        return '—'
    image_preview.short_description = 'Image'


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    # Removed: email, payment_method; added phone + short_address
    list_display = [
        'id', 'full_name', 'phone', 'is_guest', 'total_amount',
        'payment_status', 'order_status', 'short_address', 'created_at',
    ]
    list_editable = ['order_status', 'payment_status']
    list_filter = ['payment_status', 'order_status', 'created_at']
    search_fields = ['id', 'first_name', 'last_name', 'email', 'phone', 'razorpay_order_id']
    readonly_fields = ['created_at', 'updated_at', 'razorpay_order_id', 'razorpay_payment_id']
    actions = [export_to_csv]
    inlines = [OrderItemInline]
    list_per_page = 25
    fieldsets = (
        ('Customer', {
            'fields': (('first_name', 'last_name'), 'email', 'phone', 'user'),
        }),
        ('Shipping', {
            'fields': (
                'shipping_address', 'apartment', 'landmark',
                'city', 'state', 'zip_code', 'country',
            ),
        }),
        ('Financials', {
            'fields': (
                'subtotal', 'discount_amount', 'shipping_fee',
                'cod_fee', 'tax_amount', 'total_amount',
                'coupon_code', 'exchange_code_used',
            ),
        }),
        ('Payment & Status', {
            'fields': (
                'payment_method', 'payment_status', 'order_status',
                'delivered_at', 'razorpay_order_id', 'razorpay_payment_id',
            ),
        }),
        ('Policy', {'fields': ('accepted_return_policy',)}),
        ('Tracking', {'fields': ('tracking_link', 'tracking_note')}),
        ('Timestamps', {'fields': ('created_at', 'updated_at')}),
    )

    def full_name(self, obj):
        return f'{obj.first_name} {obj.last_name}'.strip() or '—'
    full_name.short_description = 'Customer'

    def is_guest(self, obj):
        return obj.user is None
    is_guest.boolean = True
    is_guest.short_description = 'Guest?'

    def short_address(self, obj):
        parts = [p for p in [obj.city, obj.state] if p]
        return ', '.join(parts) or '—'
    short_address.short_description = 'Location'

    def save_model(self, request, obj, form, change):
        if change and 'order_status' in form.changed_data and obj.order_status == 'Delivered':
            if not obj.delivered_at:
                obj.delivered_at = timezone.now()
        super().save_model(request, obj, form, change)


# ─── Exchange Request admin ───────────────────────────────────────────────────

def approve_exchange_and_generate_code(modeladmin, request, queryset):
    for req in queryset.filter(status='Pending'):
        req.status = 'Approved'
        req.save()  # signal auto-creates ExchangeCode

approve_exchange_and_generate_code.short_description = 'Approve & generate exchange codes'


def reject_exchange(modeladmin, request, queryset):
    queryset.filter(status='Pending').update(
        status='Rejected',
        admin_notes='Your exchange request has been reviewed and rejected. Contact support if you have questions.',
    )

reject_exchange.short_description = 'Reject selected exchange requests'


@admin.register(ReturnRequest)
class ExchangeRequestAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'get_order_id', 'get_customer', 'status', 'has_video', 'created_at',
    ]
    list_filter = ['status']
    search_fields = ['order__id', 'order__email', 'order__user__email']
    readonly_fields = ['order', 'user', 'guest_email', 'created_at', 'updated_at', 'exchange_code']
    actions = [approve_exchange_and_generate_code, reject_exchange]
    list_per_page = 25

    def get_order_id(self, obj):
        return f'#{obj.order_id}'
    get_order_id.short_description = 'Order'

    def get_customer(self, obj):
        if obj.user:
            return obj.user.email
        return obj.guest_email or obj.order.email or '—'
    get_customer.short_description = 'Customer'

    def has_video(self, obj):
        return bool(obj.defect_video_url)
    has_video.boolean = True
    has_video.short_description = 'Video?'


# ─── Return Request admin ─────────────────────────────────────────────────────

def approve_return(modeladmin, request, queryset):
    queryset.filter(status='Pending').update(status='Approved')

approve_return.short_description = 'Approve selected return requests'


def reject_return(modeladmin, request, queryset):
    queryset.filter(status='Pending').update(
        status='Rejected',
        admin_notes='Your return request has been reviewed and rejected. Contact support if needed.',
    )

reject_return.short_description = 'Reject selected return requests'


@admin.register(OrderReturnRequest)
class OrderReturnRequestAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'get_order_id', 'get_customer', 'status',
        'refund_initiated', 'has_video', 'created_at',
    ]
    list_filter = ['status', 'refund_initiated']
    search_fields = ['order__id', 'order__email', 'order__user__email']
    readonly_fields = ['order', 'user', 'guest_email', 'created_at', 'updated_at']
    actions = [approve_return, reject_return]
    list_per_page = 25
    fieldsets = (
        ('Request', {'fields': ('order', 'user', 'guest_email', 'reason', 'video_url')}),
        ('Status', {'fields': ('status', 'admin_notes')}),
        ('Refund', {'fields': ('refund_initiated', 'razorpay_refund_id')}),
        ('Timestamps', {'fields': ('created_at', 'updated_at')}),
    )

    def get_order_id(self, obj):
        return f'#{obj.order_id}'
    get_order_id.short_description = 'Order'

    def get_customer(self, obj):
        if obj.user:
            return obj.user.email
        return obj.guest_email or obj.order.email or '—'
    get_customer.short_description = 'Customer'

    def has_video(self, obj):
        return bool(obj.video_url)
    has_video.boolean = True
    has_video.short_description = 'Video?'


# ─── Exchange Code admin ──────────────────────────────────────────────────────

@admin.register(ExchangeCode)
class ExchangeCodeAdmin(admin.ModelAdmin):
    list_display = [
        'code', 'get_order', 'original_order_value', 'is_used', 'expires_at', 'created_at',
    ]
    list_filter = ['is_used']
    search_fields = ['code', 'order__id']
    readonly_fields = ['code', 'created_at', 'used_at']
    list_per_page = 25

    def get_order(self, obj):
        return f'Order #{obj.order_id}'
    get_order.short_description = 'Order'