from decimal import Decimal
from html.parser import HTMLParser
from functools import lru_cache
from pathlib import Path


class _MenuCatalogParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.catalog = {}
        self._item = None
        self._target = None

    def handle_starttag(self, tag, attrs):
        if tag == "li":
            self._item = {"name": [], "price": []}
            self._target = None
        elif tag == "span" and self._item is not None:
            attributes = dict(attrs)
            classes = attributes.get("class", "").split()
            if "menu-price" in classes:
                self._target = "price"
            elif not self._item["name"]:
                self._target = "name"

    def handle_data(self, data):
        if self._item is not None and self._target:
            self._item[self._target].append(data)

    def handle_endtag(self, tag):
        if tag == "span":
            self._target = None
        elif tag == "li" and self._item is not None:
            name = " ".join("".join(self._item["name"]).split())
            price_text = "".join(self._item["price"]).replace("₹", "").strip()
            if name and price_text:
                price = Decimal(price_text)
                existing_price = self.catalog.get(name)
                if existing_price is not None and existing_price != price:
                    raise ValueError(f"Conflicting menu prices for {name}.")
                self.catalog[name] = price
            self._item = None
            self._target = None


@lru_cache(maxsize=1)
def get_menu_catalog():
    menu_path = (
        Path(__file__).resolve().parent.parent
        / "templates"
        / "customer"
        / "menu.html"
    )
    parser = _MenuCatalogParser()
    parser.feed(menu_path.read_text(encoding="utf-8"))
    return parser.catalog
