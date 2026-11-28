from django.contrib import admin
from django.utils.html import format_html

from .models import (
    CategoryItem, DeliveryBand, DeliverySettings, HotelSettings, MenuCategory,
    MenuItem, MenuVariant, Order, OrderItem,
)


class MenuVariantInline(admin.TabularInline):
    model = MenuVariant
    extra = 0
    min_num = 1
    validate_min = True


class CategoryItemInline(admin.TabularInline):
    model = CategoryItem
    extra = 0
    autocomplete_fields = ("category",)


@admin.register(MenuItem)
class MenuItemAdmin(admin.ModelAdmin):
    list_display = ("name", "available", "featured")
    list_filter = ("available", "featured")
    search_fields = ("name",)
    inlines = (MenuVariantInline, CategoryItemInline)


@admin.register(MenuCategory)
class MenuCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "position", "available")
    list_editable = ("position", "available")
    search_fields = ("name", "tags")


class SingletonAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not self.model.objects.exists() and super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(HotelSettings)
class HotelSettingsAdmin(SingletonAdmin):
    pass


@admin.register(DeliverySettings)
class DeliverySettingsAdmin(SingletonAdmin):
    pass


@admin.register(DeliveryBand)
class DeliveryBandAdmin(admin.ModelAdmin):
    list_display = ("max_distance_km", "charge")
    list_editable = ("charge",)


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("name", "quantity", "unit_price")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "order_number",
        "customer_name",
        "mobile",
        "fulfillment",
        "total",
        "status",
        "created_at",
    )
    list_filter = ("fulfillment", "status", "created_at")
    search_fields = (
        "order_number",
        "customer_name",
        "mobile",
        "customer__email",
        "address",
    )
    readonly_fields = (
        "order_number", "customer", "customer_name", "mobile", "fulfillment",
        "address", "city", "pincode", "landmark", "latitude", "longitude",
        "delivery_distance_km", "subtotal", "delivery_charge", "total",
        "payment_method", "created_at", "updated_at", "pinned_location",
    )
    inlines = (OrderItemInline,)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Pinned delivery location")
    def pinned_location(self, order):
        if order.latitude is None or order.longitude is None:
            return "Not applicable"
        return format_html(
            '<a href="https://www.google.com/maps/search/?api=1&query={},{}" '
            'target="_blank" rel="noopener">Open in Google Maps</a>',
            order.latitude,
            order.longitude,
        )
