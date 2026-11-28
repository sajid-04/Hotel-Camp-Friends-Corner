import json
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import DeliveryBand, DeliverySettings, HotelSettings, MenuCategory, MenuItem, Order, OrderItem
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
            'quoted_delivery_charge': '30',
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

        self.assertRedirects(response, reverse('cart'))
        self.assertFalse(Order.objects.exists())
        get_distance.assert_not_called()
        response = self.client.post(
            reverse('checkout'), self.order_payload(delivery_charge='0', total='1'),
        )
        order = Order.objects.get()
        self.assertRedirects(
            response,
            reverse('order_confirmation', args=[order.pk]),
        )
        self.assertEqual(order.customer, self.customer)
        self.assertEqual(order.fulfillment, Order.Fulfillment.DELIVERY)
        self.assertEqual(order.delivery_distance_km, Decimal('3.25'))
        self.assertEqual(order.subtotal, Decimal('470.00'))
        self.assertEqual(order.delivery_charge, Decimal('30.00'))
        self.assertEqual(order.total, Decimal('500.00'))
        self.assertEqual(OrderItem.objects.filter(order=order).count(), 2)
        get_distance.assert_called_once_with(15.86, 74.5)
        self.assertContains(
            self.client.get(reverse('order_confirmation', args=[order.pk])),
            'Delivery (3.25 km)',
        )
        self.assertContains(
            self.client.get(reverse('my_orders')),
            order.order_number,
        )

    @patch('customer.views.get_driving_distance_km')
    def test_takeaway_order_needs_no_location_or_delivery_charge(self, get_distance):
        response = self.client.post(
            reverse('checkout'),
            self.order_payload(
                fulfillment='takeaway',
                address='', city='', pincode='', latitude='', longitude='',
                delivery_charge='500',
            ),
        )

        order = Order.objects.get()
        self.assertRedirects(response, reverse('order_confirmation', args=[order.pk]))
        self.assertEqual(order.fulfillment, Order.Fulfillment.TAKEAWAY)
        self.assertEqual(order.address, '')
        self.assertIsNone(order.latitude)
        self.assertIsNone(order.longitude)
        self.assertIsNone(order.delivery_distance_km)
        self.assertEqual(order.delivery_charge, Decimal('0.00'))
        self.assertEqual(order.total, Decimal('470.00'))
        get_distance.assert_not_called()
        confirmation = self.client.get(reverse('order_confirmation', args=[order.pk]))
        self.assertContains(confirmation, 'Collect from Hotel Camp Friends Corner')
        self.assertContains(confirmation, 'Cash on Collection')
        self.assertNotContains(confirmation, 'Delivery (')
        self.assertContains(self.client.get(reverse('my_orders')), 'Takeaway')

    def test_delivery_line_only_appears_in_delivery_checkout(self):
        takeaway = self.client.get(reverse('checkout'), {'fulfillment': 'takeaway'})
        delivery = self.client.get(reverse('checkout'), {'fulfillment': 'delivery'})

        self.assertNotContains(takeaway, 'id="checkoutDelivery"')
        self.assertContains(delivery, 'id="checkoutDelivery"')

    @patch('customer.views.get_driving_distance_km', return_value=3.25)
    def test_delivery_quote_and_order_do_not_require_house_number(self, get_distance):
        response = self.client.post(reverse('calculate_delivery'), {
            'latitude': '15.860000', 'longitude': '74.500000',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            'success': True, 'distance': 3.2, 'delivery_charge': 30,
        })

        response = self.client.post(
            reverse('checkout'), self.order_payload(address='')
        )
        order = Order.objects.get()
        self.assertRedirects(response, reverse('order_confirmation', args=[order.pk]))
        self.assertEqual(order.address, '')
        self.assertEqual(order.delivery_charge, Decimal('30.00'))
        self.assertEqual(order.total, Decimal('500.00'))
        self.assertEqual(get_distance.call_count, 2)

    @patch('customer.views.get_driving_distance_km')
    def test_delivery_rejects_invalid_coordinates_or_oversized_house_number(self, get_distance):
        response = self.client.post(reverse('calculate_delivery'), {
            'latitude': 'nan', 'longitude': '74.5',
        })
        self.assertEqual(response.status_code, 400)
        response = self.client.post(
            reverse('checkout'), self.order_payload(address='x' * 256)
        )
        self.assertRedirects(response, reverse('checkout') + '?fulfillment=delivery')
        self.assertFalse(Order.objects.exists())
        get_distance.assert_not_called()

    def test_takeaway_validation_error_keeps_selected_type(self):
        response = self.client.post(
            reverse('checkout'), self.order_payload(fulfillment='takeaway', mobile='')
        )
        self.assertRedirects(response, reverse('checkout') + '?fulfillment=takeaway')
        self.assertFalse(Order.objects.exists())

    @patch('customer.views.get_driving_distance_km')
    def test_delivery_still_requires_a_location(self, get_distance):
        response = self.client.post(
            reverse('checkout'),
            self.order_payload(fulfillment='delivery', address='', latitude='', longitude=''),
        )
        self.assertRedirects(response, reverse('checkout') + '?fulfillment=delivery')
        self.assertFalse(Order.objects.exists())
        get_distance.assert_not_called()

    def test_invalid_fulfillment_is_rejected(self):
        response = self.client.post(
            reverse('checkout'), self.order_payload(fulfillment='unknown')
        )
        self.assertRedirects(response, reverse('cart'))
        self.assertFalse(Order.objects.exists())

    def test_takeaway_checkout_preserved_through_signin(self):
        self.client.logout()
        checkout_url = reverse('checkout') + '?fulfillment=takeaway'
        response = self.client.get(checkout_url)
        signin_url = response.url
        self.assertTrue(signin_url.startswith(reverse('signin') + '?next='))
        self.assertContains(self.client.get(signin_url), 'name="next" value="/checkout/?fulfillment=takeaway"')
        response = self.client.post(signin_url, {
            'email': 'customer@example.com',
            'password': 'test-password',
            'next': checkout_url,
        })
        self.assertRedirects(response, checkout_url)
        page = self.client.get(checkout_url)
        self.assertContains(page, 'name="fulfillment" value="takeaway"')
        self.assertContains(page, 'disabled hidden')
        self.assertContains(page, 'Cash on Collection')

    def test_signin_rejects_external_next_url(self):
        self.client.logout()
        response = self.client.post(reverse('signin'), {
            'email': 'customer@example.com',
            'password': 'test-password',
            'next': 'https://example.com/',
        })
        self.assertRedirects(response, reverse('account'))

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


class HotelManagementTests(TestCase):
    setUp = CheckoutOrderTests.setUp
    order_payload = CheckoutOrderTests.order_payload

    def test_menu_changes_apply_to_display_featured_and_checkout(self):
        item = MenuItem.objects.get(name='Chicken Dum Biryani')
        variant = item.variants.get()
        variant.price = Decimal('215.00')
        variant.save()

        page = self.client.get(reverse('menu'))
        self.assertContains(page, 'Chicken Dum Biryani')
        self.assertContains(page, '₹215.00')
        self.assertEqual(get_menu_catalog()['Chicken Dum Biryani'], Decimal('215.00'))

        response = self.client.post(reverse('checkout'), self.order_payload(
            fulfillment='takeaway',
            cart_data=json.dumps([{'name': item.name, 'price': 190, 'quantity': 1}]),
        ))
        self.assertRedirects(response, reverse('cart'))
        self.assertFalse(Order.objects.exists())
        response = self.client.post(reverse('checkout'), self.order_payload(
            fulfillment='takeaway',
            cart_data=json.dumps([{'name': item.name, 'price': 215, 'quantity': 1}]),
        ))
        order = Order.objects.get()
        self.assertRedirects(response, reverse('order_confirmation', args=[order.pk]))
        self.assertEqual(order.subtotal, Decimal('215.00'))

        item.available = False
        item.save()
        self.assertNotContains(self.client.get(reverse('menu')), 'Chicken Dum Biryani')
        self.assertNotIn(item.name, get_menu_catalog())

    def test_disabling_category_removes_its_items_from_checkout(self):
        category = MenuCategory.objects.get(name='DESSERTS')
        category.available = False
        category.save()
        self.assertNotContains(self.client.get(reverse('menu')), 'Caramel Pudding')
        self.assertNotIn('Caramel Pudding', get_menu_catalog())

    @patch('customer.views.get_driving_distance_km', return_value=3.25)
    def test_admin_delivery_rate_is_used_for_quote_and_order(self, route):
        band = DeliveryBand.objects.get(max_distance_km=4)
        band.charge = Decimal('47.50')
        band.save()
        quote = self.client.post(reverse('calculate_delivery'), {
            'latitude': '15.86', 'longitude': '74.5',
        })
        self.assertEqual(quote.json()['delivery_charge'], 47.5)
        self.client.post(reverse('checkout'), self.order_payload(quoted_delivery_charge='47.50'))
        self.assertEqual(Order.objects.get().delivery_charge, Decimal('47.50'))

    @patch('customer.views.get_driving_distance_km', return_value=3.25)
    def test_changed_delivery_charge_requires_review(self, route):
        band = DeliveryBand.objects.get(max_distance_km=4)
        band.charge = Decimal('47.50')
        band.save()
        response = self.client.post(reverse('checkout'), self.order_payload())
        self.assertRedirects(response, reverse('checkout') + '?fulfillment=delivery')
        self.assertFalse(Order.objects.exists())

    @patch('customer.views.get_driving_distance_km', return_value=3.25)
    def test_delivery_beyond_maximum_is_rejected(self, route):
        settings = DeliverySettings.objects.get(pk=1)
        settings.maximum_distance_km = Decimal('3.00')
        settings.save()
        quote = self.client.post(reverse('calculate_delivery'), {
            'latitude': '15.86', 'longitude': '74.5',
        })
        self.assertEqual(quote.status_code, 400)
        self.assertIn('outside our delivery area', quote.json()['message'])
        self.client.post(reverse('checkout'), self.order_payload())
        self.assertFalse(Order.objects.exists())

    def test_hotel_details_are_displayed(self):
        hotel = HotelSettings.objects.get(pk=1)
        hotel.address = 'Updated restaurant address'
        hotel.opening_hours = '10 AM to 9 PM'
        hotel.save()
        for page in ('home', 'menu'):
            response = self.client.get(reverse(page))
            self.assertContains(response, hotel.address)
            self.assertContains(response, hotel.opening_hours)

    def test_dashboard_requires_staff_and_order_permission(self):
        self.assertEqual(self.client.get(reverse('hotel_dashboard')).status_code, 302)
        self.customer.is_staff = True
        self.customer.save()
        self.assertEqual(self.client.get(reverse('hotel_dashboard')).status_code, 403)

    def test_dashboard_excludes_cancelled_order_value(self):
        staff = User.objects.create_superuser('staff', 'staff@example.com', 'test-password')
        for status, total in [(Order.Status.NEW, 100), (Order.Status.COMPLETED, 200),
                              (Order.Status.CANCELLED, 500)]:
            Order.objects.create(
                customer=self.customer, customer_name='Test Customer', mobile='9876543210',
                fulfillment=Order.Fulfillment.TAKEAWAY, subtotal=total, delivery_charge=0,
                total=total, status=status,
            )
        self.client.force_login(staff)
        response = self.client.get(reverse('hotel_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['sales']['count'], 2)
        self.assertEqual(response.context['sales']['total'], Decimal('300.00'))
        self.assertEqual(response.context['active_count'], 1)
        filtered = self.client.get(reverse('hotel_dashboard'), {'start': '2000-01-01', 'end': '2000-12-31'})
        self.assertEqual(filtered.context['sales']['count'], 0)
        self.assertEqual(
            self.client.get(reverse('hotel_dashboard'), {'start': '2026-02-01', 'end': '2026-01-01'}).status_code,
            400,
        )

    def test_order_status_can_be_updated_in_admin(self):
        order = Order.objects.create(
            customer=self.customer, customer_name='Test Customer', mobile='9876543210',
            fulfillment=Order.Fulfillment.TAKEAWAY, subtotal=100, delivery_charge=0, total=100,
        )
        staff = User.objects.create_superuser('staff', 'staff@example.com', 'test-password')
        self.client.force_login(staff)
        response = self.client.post(reverse('admin:customer_order_change', args=[order.pk]), {
            'status': Order.Status.CONFIRMED,
            'items-TOTAL_FORMS': '0', 'items-INITIAL_FORMS': '0',
            'items-MIN_NUM_FORMS': '0', 'items-MAX_NUM_FORMS': '1000',
            '_save': 'Save',
        })
        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CONFIRMED)
        self.assertEqual(self.client.get(reverse('admin:customer_order_delete', args=[order.pk])).status_code, 403)

    @patch('customer.views.get_menu_catalog', side_effect=ValueError('conflict'))
    def test_conflicting_menu_blocks_checkout(self, catalog):
        with self.assertLogs('customer.views', level='ERROR'):
            response = self.client.get(reverse('checkout'), follow=True)
        self.assertRedirects(response, reverse('cart'))
        self.assertContains(response, 'menu is temporarily unavailable')

    def test_staff_can_add_a_menu_item_through_admin(self):
        staff = User.objects.create_superuser('staff', 'staff@example.com', 'test-password')
        self.client.force_login(staff)
        category = MenuCategory.objects.get(name='DESSERTS')
        response = self.client.post(reverse('admin:customer_menuitem_add'), {
            'name': 'New Dessert', 'available': 'on', 'featured_position': '0',
            'variants-TOTAL_FORMS': '1', 'variants-INITIAL_FORMS': '0',
            'variants-MIN_NUM_FORMS': '1', 'variants-MAX_NUM_FORMS': '1000',
            'variants-0-label': '', 'variants-0-price': '99.00',
            'variants-0-position': '0', 'variants-0-available': 'on',
            'category_entries-TOTAL_FORMS': '1', 'category_entries-INITIAL_FORMS': '0',
            'category_entries-MIN_NUM_FORMS': '0', 'category_entries-MAX_NUM_FORMS': '1000',
            'category_entries-0-category': str(category.pk), 'category_entries-0-position': '0',
            '_save': 'Save',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(get_menu_catalog()['New Dessert'], Decimal('99.00'))
        self.assertContains(self.client.get(reverse('menu')), 'New Dessert')

    @override_settings(GOOGLE_MAPS_SERVER_API_KEY='server-key')
    @patch('customer.views.requests.post')
    def test_route_uses_editable_restaurant_location(self, post):
        hotel = HotelSettings.objects.get(pk=1)
        hotel.latitude, hotel.longitude = Decimal('15.9000000'), Decimal('74.6000000')
        hotel.save()
        post.return_value.json.return_value = {'routes': [{'distanceMeters': 1000}]}
        get_driving_distance_km(15.86, 74.5)
        self.assertEqual(post.call_args.kwargs['json']['origin']['location']['latLng'], {
            'latitude': 15.9, 'longitude': 74.6,
        })
