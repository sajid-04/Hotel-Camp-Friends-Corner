from django.db.models import Prefetch

from .models import CategoryItem, MenuCategory, MenuItem, MenuVariant


def available_variants():
    return MenuVariant.objects.filter(
        available=True,
        item__available=True,
        item__category_entries__category__available=True,
    ).select_related("item").distinct()


def get_menu_catalog():
    catalog = {}
    for variant in available_variants():
        name = variant.cart_name
        if name in catalog:
            raise ValueError(f"Conflicting menu names for {name}.")
        catalog[name] = variant.price
    return catalog


def menu_context():
    variants = MenuVariant.objects.filter(available=True).select_related("item")
    entries = CategoryItem.objects.filter(item__available=True, item__variants__available=True).distinct().select_related("item").prefetch_related(
        Prefetch("item__variants", queryset=variants, to_attr="visible_variants"),
    )
    categories = MenuCategory.objects.filter(
        available=True, entries__item__available=True, entries__item__variants__available=True,
    ).distinct().prefetch_related(
        Prefetch("entries", queryset=entries, to_attr="visible_entries"),
    )
    featured = MenuItem.objects.filter(
        featured=True, available=True, category_entries__category__available=True,
    ).distinct().prefetch_related(
        Prefetch("variants", queryset=variants, to_attr="visible_variants"),
        "categories",
    ).order_by("featured_position", "name")
    featured_cards = []
    for item in featured:
        for variant in item.visible_variants:
            featured_cards.append({
                "item": item,
                "variant": variant,
                "tags": " ".join(category.tags for category in item.categories.all() if category.available),
            })
    return {"menu_categories": categories, "featured_cards": featured_cards}
