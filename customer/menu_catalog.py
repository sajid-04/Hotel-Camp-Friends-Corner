import re
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
        self._reading_portion_heading = False
        self._reading_heading_span = False
        self._heading_span = []
        self._portion_heading = []
        self._portion_labels = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = attributes.get("class", "").split()

        if tag == "div" and "menu-card" in classes:
            self._portion_labels = []
        elif tag == "div" and "price-heading" in classes:
            self._reading_portion_heading = True
            self._portion_heading = []
        elif tag == "span" and self._reading_portion_heading:
            self._reading_heading_span = True
            self._heading_span = []

        if tag == "li":
            self._item = {"name": [], "price": []}
            self._target = None
        elif tag == "span" and self._item is not None:
            if "menu-price" in classes:
                self._target = "price"
            elif not self._item["name"]:
                self._target = "name"

    def handle_data(self, data):
        if self._reading_heading_span:
            self._heading_span.append(data)
        if self._item is not None and self._target:
            self._item[self._target].append(data)

    def handle_endtag(self, tag):
        if tag == "span":
            self._target = None
            if self._reading_heading_span:
                label = " ".join("".join(self._heading_span).split())
                if label and label.lower() != "dish":
                    self._portion_heading.append(label)
                self._reading_heading_span = False
                self._heading_span = []
        elif tag == "div" and self._reading_portion_heading:
            self._portion_labels = self._portion_heading
            self._portion_heading = []
            self._reading_portion_heading = False
        elif tag == "li" and self._item is not None:
            name = " ".join("".join(self._item["name"]).split())
            prices = []
            for index, price_text in enumerate(self._item["price"]):
                normalized_price = (
                    price_text.replace("₹", "")
                    .replace(",", "")
                    .replace("/", "")
                    .strip()
                )
                if re.fullmatch(r"\d+(?:\.\d{1,2})?", normalized_price):
                    prices.append((index, Decimal(normalized_price)))

            if name and prices:
                if len(self._item["price"]) == 1:
                    self._add_item(name, prices[0][1])
                else:
                    for index, price in prices:
                        label = (
                            self._portion_labels[index]
                            if index < len(self._portion_labels)
                            else ("Qtr." if index == 0 else "Half")
                        )
                        self._add_item(f"{name} - {label}", price)

            self._item = None
            self._target = None

    def _add_item(self, name, price):
        existing_price = self.catalog.get(name)
        if existing_price is not None and existing_price != price:
            raise ValueError(f"Conflicting menu prices for {name}.")
        self.catalog[name] = price


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
