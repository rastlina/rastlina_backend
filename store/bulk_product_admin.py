from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse

from .models import Category, Product, ProductVariant


class BulkProductEditForm(forms.Form):
    """Apply only explicitly selected field values to selected products."""
    product_ids = forms.CharField(widget=forms.HiddenInput)
    apply_name = forms.BooleanField(required=False)
    name = forms.CharField(required=False, max_length=255)
    apply_price = forms.BooleanField(required=False)
    price = forms.DecimalField(required=False, max_digits=10, decimal_places=2, min_value=0)
    apply_original_price = forms.BooleanField(required=False)
    original_price = forms.DecimalField(required=False, max_digits=10, decimal_places=2, min_value=0)
    apply_category = forms.BooleanField(required=False)
    category = forms.ModelChoiceField(queryset=Category.objects.none(), required=False)
    apply_description = forms.BooleanField(required=False)
    description = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 5}))
    apply_care_instructions = forms.BooleanField(required=False)
    care_instructions = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 4}))
    apply_what_you_get = forms.BooleanField(required=False)
    what_you_get = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 4}))
    apply_is_new_arrival = forms.BooleanField(required=False)
    is_new_arrival = forms.BooleanField(required=False)
    apply_is_best_seller = forms.BooleanField(required=False)
    is_best_seller = forms.BooleanField(required=False)
    apply_is_trending = forms.BooleanField(required=False)
    is_trending = forms.BooleanField(required=False)
    apply_is_best_deal = forms.BooleanField(required=False)
    is_best_deal = forms.BooleanField(required=False)
    apply_is_active = forms.BooleanField(required=False)
    is_active = forms.BooleanField(required=False)
    apply_stock = forms.BooleanField(required=False)
    stock = forms.IntegerField(required=False, min_value=0)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = Category.objects.order_by("main_category__name", "name")

    def clean(self):
        cleaned = super().clean()
        fields = ("name", "price", "original_price", "category", "description",
                  "care_instructions", "what_you_get", "is_new_arrival", "is_best_seller",
                  "is_trending", "is_best_deal", "is_active", "stock")
        if not any(cleaned.get("apply_" + name) for name in fields):
            raise forms.ValidationError("Select at least one Apply checkbox.")
        for name in ("name", "price", "original_price", "category", "stock"):
            if cleaned.get("apply_" + name) and cleaned.get(name) in (None, ""):
                raise forms.ValidationError("Enter a value for every field you chose to apply.")
        return cleaned


def bulk_edit_selected_products(modeladmin, request, queryset):
    if not modeladmin.has_change_permission(request):
        raise PermissionDenied
    products = list(queryset.select_related("category"))
    if not products:
        modeladmin.message_user(request, "Select at least one product.", messages.WARNING)
        return None
    if any(not modeladmin.has_change_permission(request, product) for product in products):
        raise PermissionDenied

    if request.method == "POST" and "product_ids" in request.POST:
        form = BulkProductEditForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            try:
                submitted_ids = [int(value) for value in data["product_ids"].split(",") if value]
            except ValueError:
                raise PermissionDenied
            if set(submitted_ids) != {p.pk for p in products}:
                raise PermissionDenied
            changes = {}
            for field in ("name", "price", "original_price", "category", "description",
                          "care_instructions", "what_you_get", "is_new_arrival", "is_best_seller",
                          "is_trending", "is_best_deal", "is_active"):
                if data.get("apply_" + field):
                    changes[field] = data[field]
            if data.get("apply_stock"):
                without_variants = [p.name for p in products
                                    if data["stock"] > 0 and not p.variants.exists()]
                if without_variants:
                    form.add_error("stock", "Add a size/color variant before assigning stock to: "
                                   + ", ".join(without_variants))
                    context = {
                        **modeladmin.admin_site.each_context(request),
                        "title": "Bulk edit selected products",
                        "opts": modeladmin.model._meta,
                        "products": products,
                        "form": form,
                    }
                    return TemplateResponse(request, "admin/store/product/bulk_edit.html", context)
            with transaction.atomic():
                for product in products:
                    for field, value in changes.items():
                        setattr(product, field, value)
                    product.save()
                    if data.get("apply_stock"):
                        # Product stock is variant-based; preserve variant sizes/colors and
                        # distribute the requested total evenly, with remainder to first rows.
                        variants = list(ProductVariant.objects.select_for_update().filter(
                            product=product).order_by("pk"))
                        if variants:
                            total = data["stock"]
                            each, remainder = divmod(total, len(variants))
                            for index, variant in enumerate(variants):
                                variant.stock = each + (1 if index < remainder else 0)
                                variant.save(update_fields=["stock"])
            modeladmin.message_user(request, f"Updated {len(products)} selected product(s).", messages.SUCCESS)
            return HttpResponseRedirect(reverse("admin:store_product_changelist"))
    else:
        form = BulkProductEditForm(initial={"product_ids": ",".join(str(p.pk) for p in products)})

    context = {
        **modeladmin.admin_site.each_context(request),
        "title": "Bulk edit selected products",
        "opts": modeladmin.model._meta,
        "products": products,
        "form": form,
        "media": form.media,
    }
    return TemplateResponse(request, "admin/store/product/bulk_edit.html", context)


bulk_edit_selected_products.short_description = "Bulk edit selected products"
