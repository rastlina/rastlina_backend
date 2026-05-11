"""orders/admin.py"""

import csv

from django.contrib import admin
from django.http import HttpResponse
from django.utils import timezone
from django.utils.html import format_html

from .models import ExchangeCode, Order, OrderItem, ReturnRequest


# ─── CSV export action ────────────────────────────────────────────────────────

def export_to_csv(modeladmin, request, queryset):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename=orders.csv'
    writer = csv.writer(response)
    writer.writerow([
        'Order ID', 'Name', 'Email', 'Phone', 'Total',
        'Payment Method', 'Payment Status', 'Order Status',
        'City', 'State', 'Date',
    ])
    for o in queryset:
        writer.writerow([
            o.id, f"{o.first_name} {o.last_name}", o.email, o.phone,
            o.total_amount, o.payment_method, o.payment_status, o.order_status,
            o.city, o.state,
            timezone.localtime(o.created_at).strftime('%d-%m-%Y %H:%M'),
        ])
    return response

export_to_csv.short_description = 'Export selected orders to CSV'


# ─── Inline ───────────────────────────────────────────────────────────────────

class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ['product_name', 'variant_label', 'price', 'quantity', 'image_preview']

    def image_preview(self, obj):
        if obj.image_url:
            return format_html('<img src="{}" style="width:50px;height:auto;" />', obj.image_url)
        return '—'
    image_preview.short_description = 'Image'


# ─── Order admin ──────────────────────────────────────────────────────────────

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'full_name', 'email', 'is_guest', 'total_amount',
        'payment_method', 'payment_status', 'order_status', 'created_at',
    ]
    list_editable = ['order_status', 'payment_status']
    list_filter = ['payment_status', 'order_status', 'payment_method', 'created_at']
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
        return f"{obj.first_name} {obj.last_name}".strip() or '—'
    full_name.short_description = 'Customer'

    def is_guest(self, obj):
        return obj.user is None
    is_guest.boolean = True
    is_guest.short_description = 'Guest?'

    def save_model(self, request, obj, form, change):
        if change and 'order_status' in form.changed_data and obj.order_status == 'Delivered':
            if not obj.delivered_at:
                obj.delivered_at = timezone.now()
        super().save_model(request, obj, form, change)


# ─── Return request actions ───────────────────────────────────────────────────

def approve_and_generate_code(modeladmin, request, queryset):
    for req in queryset.filter(status='Pending'):
        req.status = 'Approved'
        req.save()  # signal auto-creates ExchangeCode

approve_and_generate_code.short_description = 'Approve selected & generate exchange codes'


def reject_request(modeladmin, request, queryset):
    queryset.filter(status='Pending').update(
        status='Rejected',
        admin_notes='Your exchange request has been reviewed and rejected. Contact support if you have questions.',
    )

reject_request.short_description = 'Reject selected requests'


@admin.register(ReturnRequest)
class ReturnRequestAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'get_order_id', 'get_customer', 'request_type',
        'status', 'has_video', 'created_at',
    ]
    list_filter = ['status', 'request_type']
    search_fields = ['order__id', 'order__email', 'order__user__email']
    readonly_fields = ['order', 'user', 'guest_email', 'created_at', 'updated_at', 'exchange_code']
    actions = [approve_and_generate_code, reject_request]
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


@admin.register(ExchangeCode)
class ExchangeCodeAdmin(admin.ModelAdmin):
    list_display = [
        'code', 'get_order', 'original_order_value',
        'is_used', 'expires_at', 'created_at',
    ]
    list_filter = ['is_used']
    search_fields = ['code', 'order__id']
    readonly_fields = ['code', 'created_at', 'used_at']
    list_per_page = 25

    def get_order(self, obj):
        return f'Order #{obj.order_id}'
    get_order.short_description = 'Order'