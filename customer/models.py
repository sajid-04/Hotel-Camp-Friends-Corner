from django.conf import settings
from django.db import models


class Order(models.Model):

    STATUS_PLACED = 'placed'
    STATUS_CHOICES = [
        (STATUS_PLACED, 'Placed'),
        ('preparing', 'Preparing'),
        ('out_for_delivery', 'Out for Delivery'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
    ]

    PAYMENT_COD = 'cod'
    PAYMENT_CHOICES = [
        (PAYMENT_COD, 'Cash on Delivery'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='orders')
    full_name = models.CharField(max_length=150)
    mobile = models.CharField(max_length=10)
    address = models.CharField(max_length=255)
    landmark = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100)
    pincode = models.CharField(max_length=6)
    latitude = models.FloatField()
    longitude = models.FloatField()
    payment_method = models.CharField(max_length=20, choices=PAYMENT_CHOICES, default=PAYMENT_COD)
    delivery_distance_km = models.FloatField()
    delivery_charge = models.PositiveIntegerField()
    subtotal = models.PositiveIntegerField()
    total = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PLACED)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Order #{self.id} - {self.full_name}"


class OrderItem(models.Model):

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    name = models.CharField(max_length=200)
    price = models.PositiveIntegerField()
    quantity = models.PositiveIntegerField(default=1)

    @property
    def total_price(self):
        return self.price * self.quantity

    def __str__(self):
        return f"{self.name} x {self.quantity}"
