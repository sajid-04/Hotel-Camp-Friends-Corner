from django.contrib import admin
from django.utils.html import format_html

from .models import Order, OrderItem


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("name", "quantity", "unit_price")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "order_number",
        "customer_name",
        "mobile",
        "total",
        "status",
        "created_at",
    )
    list_filter = ("status", "created_at")
    search_fields = (
        "order_number",
        "customer_name",
        "mobile",
        "customer__email",
        "address",
    )
    readonly_fields = (
        "order_number",
        "created_at",
        "updated_at",
        "pinned_location",
    )
    inlines = (OrderItemInline,)

    @admin.display(description="Pinned delivery location")
    def pinned_location(self, order):
        return format_html(
            '<a href="https://www.google.com/maps/search/?api=1&query={},{}" '
            'target="_blank" rel="noopener">Open in Google Maps</a>',
            order.latitude,
            order.longitude,
        )
