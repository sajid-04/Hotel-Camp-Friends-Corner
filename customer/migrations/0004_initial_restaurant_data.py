import json
from pathlib import Path

from django.db import migrations


def load_initial_data(apps, schema_editor):
    Category = apps.get_model("customer", "MenuCategory")
    Item = apps.get_model("customer", "MenuItem")
    Entry = apps.get_model("customer", "CategoryItem")
    Variant = apps.get_model("customer", "MenuVariant")
    HotelSettings = apps.get_model("customer", "HotelSettings")
    DeliverySettings = apps.get_model("customer", "DeliverySettings")
    DeliveryBand = apps.get_model("customer", "DeliveryBand")
    db = schema_editor.connection.alias

    data = json.loads(Path(__file__).with_name("initial_menu.json").read_text(encoding="utf-8"))
    for category_position, category_data in enumerate(data):
        category = Category.objects.using(db).create(
            name=category_data["name"], tags=category_data["tags"], position=category_position,
        )
        for item_position, item_data in enumerate(category_data["items"]):
            item, created = Item.objects.using(db).get_or_create(name=item_data["name"])
            Entry.objects.using(db).create(category=category, item=item, position=item_position)
            if created:
                for position, variant in enumerate(item_data["variants"]):
                    Variant.objects.using(db).create(item=item, position=position, **variant)

    featured = [
        ("Chl. Drum Stick (6 Pieces)", "Chicken Drum Stick", "CHICKEN STARTER", "chicken-drum-stick.jpg"),
        ("Chl. Adraki Kabab", "Chicken Adraki Kabab", "KABAB", "chicken-adraki-kabab.jpg"),
        ("Chl. Chilly", "Chicken Chilly", "CHICKEN STARTER", "chicken-chilly.jpg"),
        ("Chicken Dum Biryani", "Chicken Dum Biryani", "BIRYANI", "chicken-dum-biryani.jpg"),
        ("Chl. Loly Pop (6 Pieces)", "Chicken Lollipop", "CHICKEN STARTER", "chicken-lollipop.jpg"),
        ("Chl. Shahi Butter Tandoor with Bone", "Chicken Shahi Butter Tandoor", "CHICKEN STARTER", "chicken-shahi-butter-tandoor.jpg"),
    ]
    for position, (name, title, label, image) in enumerate(featured):
        Item.objects.using(db).filter(name=name).update(
            featured=True, featured_name=title, featured_category=label,
            featured_image=f"customer/images/{image}", featured_position=position,
        )

    HotelSettings.objects.using(db).create()
    DeliverySettings.objects.using(db).create()
    for distance, charge in [(2, 20), (4, 30), (6, 40), (8, 50), (10, 60)]:
        DeliveryBand.objects.using(db).create(max_distance_km=distance, charge=charge)


class Migration(migrations.Migration):
    dependencies = [("customer", "0003_deliveryband_deliverysettings_hotelsettings_and_more")]
    operations = [migrations.RunPython(load_initial_data, migrations.RunPython.noop)]
