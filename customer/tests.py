import json
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Order, OrderItem
from .menu_catalog import get_menu_catalog
from .views import get_driving_distance_km


class CheckoutOrderTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username='customer@example.com',
            email='customer@example.com',
            password='test-password',
        )
        self.client.force_login(self.customer)

    def order_payload(self, **overrides):
        payload = {
            'full_name': 'Test Customer',
            'mobile': '9876543210',
            'address': 'House 10',
            'city': 'Belagavi',
            'pincode': '590001',
            'latitude': '15.860000',
            'longitude': '74.500000',
            'payment_method': 'cod',
            'cart_data': json.dumps([
                {'name': 'Chicken Dum Biryani', 'price': 190, 'quantity': 2},
                {'name': 'Plain Rice', 'price': 90, 'quantity': 1},
            ]),
        }
        payload.update(overrides)
        return payload

    def test_menu_catalog_parses_portions_and_unavailable_prices(self):
        catalog = get_menu_catalog()

        self.assertEqual(
            catalog['Chl. Masala - Qtr. (4 Piece)'],
            Decimal('240'),
        )
        self.assertEqual(
            catalog['Chl. Masala - Half (8 Piece)'],
            Decimal('400'),
        )
        self.assertIn('Chl. Dry Fry (7 Piece) - Qtr. (4 Piece)', catalog)
        self.assertNotIn('Chl. Dry Fry (7 Piece) - Half (8 Piece)', catalog)

    @patch('customer.views.get_driving_distance_km', return_value=3.25)
    def test_place_order_saves_items_and_server_calculated_delivery(self, get_distance):
        cart_data = json.loads(self.order_payload()['cart_data'])
        cart_data[0]['price'] = 1
        cart_data[1]['price'] = 999999
        response = self.client.post(
            reverse('checkout'),
            self.order_payload(
                cart_data=json.dumps(cart_data),
                delivery_charge='0',
                total='1',
            ),
        )

        order = Order.objects.get()
        self.assertRedirects(
            response,
            reverse('order_confirmation', args=[order.pk]),
        )
        self.assertEqual(order.customer, self.customer)
        self.assertEqual(order.delivery_distance_km, Decimal('3.25'))
        self.assertEqual(order.subtotal, Decimal('470.00'))
        self.assertEqual(order.delivery_charge, Decimal('30.00'))
        self.assertEqual(order.total, Decimal('500.00'))
        self.assertEqual(OrderItem.objects.filter(order=order).count(), 2)
        get_distance.assert_called_once_with(15.86, 74.5)
        self.assertContains(
            self.client.get(reverse('my_orders')),
            order.order_number,
        )

    @patch('customer.views.get_driving_distance_km')
    def test_invalid_cart_does_not_create_order(self, get_distance):
        response = self.client.post(
            reverse('checkout'),
            self.order_payload(cart_data='[]'),
        )

        self.assertRedirects(response, reverse('cart'))
        self.assertFalse(Order.objects.exists())
        get_distance.assert_not_called()

    @patch('customer.views.get_driving_distance_km')
    def test_unknown_menu_item_does_not_create_order(self, get_distance):
        response = self.client.post(
            reverse('checkout'),
            self.order_payload(
                cart_data=json.dumps([
                    {'name': 'Customer-chosen item', 'price': 1, 'quantity': 1},
                ]),
            ),
        )

        self.assertRedirects(response, reverse('cart'))
        self.assertFalse(Order.objects.exists())
        get_distance.assert_not_called()

    def test_customer_cannot_view_another_customers_order(self):
        other_customer = User.objects.create_user(
            username='other@example.com',
            email='other@example.com',
            password='test-password',
        )
        order = Order.objects.create(
            customer=other_customer,
            customer_name='Other Customer',
            mobile='9876543210',
            address='House 10',
            city='Belagavi',
            pincode='590001',
            latitude=Decimal('15.860000'),
            longitude=Decimal('74.500000'),
            delivery_distance_km=Decimal('1.00'),
            subtotal=Decimal('100.00'),
            delivery_charge=Decimal('20.00'),
            total=Decimal('120.00'),
        )

        response = self.client.get(
            reverse('order_confirmation', args=[order.pk])
        )

        self.assertEqual(response.status_code, 404)

    @override_settings(GOOGLE_MAPS_BROWSER_API_KEY='maps-browser-key')
    def test_checkout_renders_configured_google_maps_key(self):
        response = self.client.get(reverse('checkout'))

        self.assertEqual(
            response.context['google_maps_browser_api_key'],
            'maps-browser-key',
        )
        self.assertContains(response, r'maps\u002Dbrowser\u002Dkey')
        self.assertContains(response, 'Choose Location on Map')
        self.assertContains(response, 'gestureHandling: "greedy"')

    @override_settings(GOOGLE_MAPS_SERVER_API_KEY='server-key')
    @patch('customer.views.requests.post')
    def test_google_route_uses_driving_distance_in_metres(self, post):
        post.return_value.json.return_value = {'routes': [{'distanceMeters': 3250}]}

        self.assertEqual(get_driving_distance_km(15.86, 74.5), 3.25)
        args, kwargs = post.call_args
        self.assertEqual(args[0], 'https://routes.googleapis.com/directions/v2:computeRoutes')
        self.assertEqual(kwargs['headers']['X-Goog-FieldMask'], 'routes.distanceMeters')
        self.assertEqual(kwargs['headers']['X-Goog-Api-Key'], 'server-key')
        self.assertEqual(kwargs['json']['travelMode'], 'DRIVE')
        self.assertEqual(
            kwargs['json']['destination']['location']['latLng'],
            {'latitude': 15.86, 'longitude': 74.5},
        )

    @override_settings(GOOGLE_MAPS_SERVER_API_KEY='server-key')
    @patch('customer.views.requests.post')
    def test_google_route_rejects_missing_or_invalid_distance(self, post):
        for data in ({'routes': []}, {'routes': [{'distanceMeters': -1}]},
                     {'routes': [{}]}):
            with self.subTest(data=data):
                post.return_value.json.return_value = data
                with self.assertRaises(ValueError):
                    get_driving_distance_km(15.86, 74.5)
