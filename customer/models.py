import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from decimal import Decimal


def generate_order_number():
    return uuid.uuid4().hex[:12].upper()


class MenuCategory(models.Model):
    id = models.AutoField(auto_created=True, primary_key=True, verbose_name="ID")
    name = models.CharField(max_length=120, unique=True)
    tags = models.CharField(max_length=200, blank=True, help_text="Space-separated filter tags, such as chicken starters.")
    position = models.PositiveIntegerField(default=0)
    available = models.BooleanField(default=True)

    class Meta:
        ordering = ("position", "name")
        verbose_name_plural = "menu categories"

    def __str__(self):
        return self.name


class MenuItem(models.Model):
    id = models.AutoField(auto_created=True, primary_key=True, verbose_name="ID")
    name = models.CharField(max_length=150, unique=True, validators=[
        RegexValidator(r"^(?!.* - ).+$", "Do not use ' - ' in the name; it is reserved for portion labels."),
    ])
    categories = models.ManyToManyField(MenuCategory, through="CategoryItem", related_name="items")
    available = models.BooleanField(default=True)
    featured = models.BooleanField(default=False)
    featured_name = models.CharField(max_length=200, blank=True)
    featured_category = models.CharField(max_length=100, blank=True)
    featured_image = models.CharField(
        max_length=255, blank=True,
        help_text="Path under static files, for example customer/images/chicken-chilly.jpg.",
    )
    featured_position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class CategoryItem(models.Model):
    id = models.AutoField(auto_created=True, primary_key=True, verbose_name="ID")
    category = models.ForeignKey(MenuCategory, on_delete=models.CASCADE, related_name="entries")
    item = models.ForeignKey(MenuItem, on_delete=models.CASCADE, related_name="category_entries")
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("position", "id")
        constraints = [models.UniqueConstraint(fields=("category", "item"), name="unique_category_item")]


class MenuVariant(models.Model):
    id = models.AutoField(auto_created=True, primary_key=True, verbose_name="ID")
    item = models.ForeignKey(MenuItem, on_delete=models.CASCADE, related_name="variants")
    label = models.CharField(max_length=100, blank=True)
    price = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])
    position = models.PositiveIntegerField(default=0)
    available = models.BooleanField(default=True)

    class Meta:
        ordering = ("position", "id")
        constraints = [models.UniqueConstraint(fields=("item", "label"), name="unique_item_variant_label")]

    @property
    def cart_name(self):
        return f"{self.item.name} - {self.label}" if self.label else self.item.name

    def __str__(self):
        return self.cart_name


class HotelSettings(models.Model):
    id = models.AutoField(auto_created=True, primary_key=True, verbose_name="ID")
    address = models.CharField(max_length=255, default="Havelock Road, Camp, Belgaum")
    opening_hours = models.CharField(max_length=120, default="11:00 AM – 11:00 PM")
    phone = models.CharField(max_length=20, default="9945449283", validators=[RegexValidator(r"^\d+$", "Use digits only.")])
    whatsapp = models.CharField(max_length=20, default="919945449283", validators=[RegexValidator(r"^\d+$", "Use digits only.")], help_text="Digits only, including country code.")
    latitude = models.DecimalField(max_digits=10, decimal_places=7, default=Decimal("15.8570643"), validators=[MinValueValidator(Decimal("-90")), MaxValueValidator(Decimal("90"))], help_text="Restaurant location used as the origin for delivery routes.")
    longitude = models.DecimalField(max_digits=10, decimal_places=7, default=Decimal("74.5040625"), validators=[MinValueValidator(Decimal("-180")), MaxValueValidator(Decimal("180"))])
    special_title = models.CharField(max_length=150, default="FRIENDS SPECIAL DUM BIRYANI")
    special_description = models.CharField(max_length=200, default="Minimum 2 Kg Order")
    special_price = models.DecimalField(max_digits=8, decimal_places=2, default=1800, validators=[MinValueValidator(Decimal("0"))])
    show_special = models.BooleanField(default=True)

    class Meta:
        verbose_name = "hotel details"
        verbose_name_plural = "hotel details"

    def __str__(self):
        return "Hotel details"


class DeliverySettings(models.Model):
    id = models.AutoField(auto_created=True, primary_key=True, verbose_name="ID")
    beyond_charge = models.DecimalField(max_digits=8, decimal_places=2, default=80, validators=[MinValueValidator(Decimal("0"))])
    maximum_distance_km = models.DecimalField(
        max_digits=7, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0.01"))],
        help_text="Leave blank for no maximum. Distances beyond the last band use the beyond charge.",
    )

    class Meta:
        verbose_name = "delivery settings"
        verbose_name_plural = "delivery settings"

    def __str__(self):
        return "Delivery settings"


class DeliveryBand(models.Model):
    id = models.AutoField(auto_created=True, primary_key=True, verbose_name="ID")
    max_distance_km = models.DecimalField(max_digits=7, decimal_places=2, unique=True, validators=[MinValueValidator(Decimal("0.01"))])
    charge = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])

    class Meta:
        ordering = ("max_distance_km",)

    def __str__(self):
        return f"Up to {self.max_distance_km} km: ₹{self.charge}"


class Order(models.Model):
    class Fulfillment(models.TextChoices):
        DELIVERY = "delivery", "Delivery"
        TAKEAWAY = "takeaway", "Takeaway"

    class Status(models.TextChoices):
        NEW = "new", "New"
        CONFIRMED = "confirmed", "Confirmed"
        PREPARING = "preparing", "Preparing"
        OUT_FOR_DELIVERY = "out_for_delivery", "Out for delivery"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    id = models.BigAutoField(primary_key=True)
    order_number = models.CharField(
        max_length=12,
        unique=True,
        default=generate_order_number,
        editable=False,
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="restaurant_orders",
    )
    customer_name = models.CharField(max_length=120)
    mobile = models.CharField(max_length=10)
    fulfillment = models.CharField(
        max_length=10, choices=Fulfillment.choices, default=Fulfillment.DELIVERY
    )
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    pincode = models.CharField(max_length=6, blank=True)
    landmark = models.CharField(max_length=255, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    delivery_distance_km = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    delivery_charge = models.DecimalField(max_digits=10, decimal_places=2)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(max_length=20, default="cod")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.NEW,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"#{self.order_number} - {self.customer_name}"


class OrderItem(models.Model):
    id = models.BigAutoField(primary_key=True)
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items",
    )
    name = models.CharField(max_length=255)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ("id",)

    @property
    def line_total(self):
        return self.unit_price * self.quantity

    def __str__(self):
        return f"{self.name} x {self.quantity}"
