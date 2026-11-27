from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("customer", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="fulfillment",
            field=models.CharField(
                choices=[("delivery", "Delivery"), ("takeaway", "Takeaway")],
                default="delivery",
                max_length=10,
            ),
        ),
        migrations.AlterField(
            model_name="order",
            name="address",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AlterField(
            model_name="order",
            name="city",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AlterField(
            model_name="order",
            name="pincode",
            field=models.CharField(blank=True, max_length=6),
        ),
        migrations.AlterField(
            model_name="order",
            name="latitude",
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True),
        ),
        migrations.AlterField(
            model_name="order",
            name="longitude",
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True),
        ),
        migrations.AlterField(
            model_name="order",
            name="delivery_distance_km",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=7, null=True),
        ),
    ]
