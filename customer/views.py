from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.http import JsonResponse
from django.conf import settings as django_settings

import json
import math
import uuid
import requests
import logging
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from .menu_catalog import get_menu_catalog
from .models import Order, OrderItem

logger = logging.getLogger(__name__)


# =========================================================
# RESTAURANT LOCATION
# =========================================================

RESTAURANT_LATITUDE = 15.8570643
RESTAURANT_LONGITUDE = 74.5040625


# =========================================================
# DELIVERY RATES - TEMPORARY
# =========================================================

def calculate_delivery_charge(distance_km):

    if distance_km <= 2:
        return 20

    if distance_km <= 4:
        return 30

    if distance_km <= 6:
        return 40

    if distance_km <= 8:
        return 50

    if distance_km <= 10:
        return 60

    return 80


def get_driving_distance_km(latitude, longitude):
    if not math.isfinite(latitude) or not math.isfinite(longitude):
        raise ValueError('The selected coordinates were invalid.')

    api_key = getattr(django_settings, 'GOOGLE_MAPS_SERVER_API_KEY', '')
    if not api_key:
        raise RuntimeError('Google Maps server API key is not configured.')

    response = requests.post(
        'https://routes.googleapis.com/directions/v2:computeRoutes',
        headers={
            'X-Goog-Api-Key': api_key,
            'X-Goog-FieldMask': 'routes.distanceMeters',
        },
        json={
            'origin': {'location': {'latLng': {
                'latitude': RESTAURANT_LATITUDE,
                'longitude': RESTAURANT_LONGITUDE,
            }}},
            'destination': {'location': {'latLng': {
                'latitude': latitude,
                'longitude': longitude,
            }}},
            'travelMode': 'DRIVE',
        },
        timeout=15,
    )
    response.raise_for_status()
    routes = response.json().get('routes', [])
    if not routes:
        raise ValueError('No driving route was returned.')

    try:
        distance_meters = float(routes[0]['distanceMeters'])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError('The route distance was invalid.') from error

    if not math.isfinite(distance_meters) or distance_meters < 0:
        raise ValueError('The route distance was invalid.')

    return distance_meters / 1000


# =========================================================
# HOME
# =========================================================

def home(request):
    return render(request, 'customer/home.html')


# =========================================================
# MENU
# =========================================================

def menu(request):
    return render(request, 'customer/menu.html')


# =========================================================
# CART
# =========================================================

def cart(request):
    return render(request, 'customer/cart.html')


# =========================================================
# CHECKOUT
# =========================================================

def checkout(request):

    if not request.user.is_authenticated:
        return redirect(f"{reverse('signin')}?{urlencode({'next': request.get_full_path()})}")

    fulfillment = (
        request.POST.get('fulfillment', Order.Fulfillment.DELIVERY)
        if request.method == 'POST'
        else request.GET.get('fulfillment', Order.Fulfillment.DELIVERY)
    )
    if fulfillment not in Order.Fulfillment.values:
        messages.error(request, 'Please choose takeaway or delivery in your cart.')
        return redirect('cart')
    checkout_url = f"{reverse('checkout')}?{urlencode({'fulfillment': fulfillment})}"

    if request.method == 'POST':
        full_name = request.POST.get('full_name', '').strip()
        mobile = request.POST.get('mobile', '').strip()
        address = request.POST.get('address', '').strip()
        city = request.POST.get('city', '').strip()
        pincode = request.POST.get('pincode', '').strip()
        landmark = request.POST.get('landmark', '').strip()

        if not full_name or len(full_name) > 120:
            messages.error(request, 'Please enter a valid full name.')
            return redirect(checkout_url)
        if not mobile.isdigit() or len(mobile) != 10:
            messages.error(request, 'Please enter a valid 10-digit mobile number.')
            return redirect(checkout_url)

        latitude = longitude = None
        if fulfillment == Order.Fulfillment.DELIVERY:
            if not address or len(address) > 255:
                messages.error(request, 'Please enter a valid house, flat or building number.')
                return redirect(checkout_url)
            if not city or len(city) > 100:
                messages.error(request, 'Please select your delivery location.')
                return redirect(checkout_url)
            if not pincode.isdigit() or len(pincode) != 6:
                messages.error(request, 'Please select a location with a valid 6-digit PIN code.')
                return redirect(checkout_url)
            if len(landmark) > 255:
                messages.error(request, 'The landmark must be 255 characters or fewer.')
                return redirect(checkout_url)

            try:
                latitude = Decimal(request.POST.get('latitude', ''))
                longitude = Decimal(request.POST.get('longitude', ''))
            except InvalidOperation:
                messages.error(request, 'Please select your delivery location on the map.')
                return redirect(checkout_url)

            if (
                not latitude.is_finite()
                or not longitude.is_finite()
                or not Decimal('6') <= latitude <= Decimal('38')
                or not Decimal('68') <= longitude <= Decimal('98')
            ):
                messages.error(request, 'The selected delivery location is invalid.')
                return redirect(checkout_url)
        else:
            address = city = pincode = landmark = ''

        try:
            submitted_items = json.loads(request.POST.get('cart_data', ''))
        except (TypeError, json.JSONDecodeError):
            messages.error(request, 'Your cart could not be read. Please review it and try again.')
            return redirect('cart')

        if (
            not isinstance(submitted_items, list)
            or not submitted_items
            or len(submitted_items) > 50
        ):
            messages.error(request, 'Your cart is empty or contains too many items.')
            return redirect('cart')

        order_items = []
        subtotal = Decimal('0.00')
        menu_catalog = get_menu_catalog()
        for item in submitted_items:
            if not isinstance(item, dict):
                messages.error(request, 'Your cart contains an invalid item.')
                return redirect('cart')

            name = item.get('name')
            quantity = item.get('quantity')
            if (
                not isinstance(name, str)
                or not name.strip()
                or len(name.strip()) > 255
                or isinstance(quantity, bool)
                or not isinstance(quantity, int)
                or not 1 <= quantity <= 99
            ):
                messages.error(request, 'Your cart contains an invalid item.')
                return redirect('cart')

            name = name.strip()
            unit_price = menu_catalog.get(name)
            if unit_price is None:
                messages.error(request, 'Your cart contains an item that is not on the menu.')
                return redirect('cart')

            subtotal += unit_price * quantity
            order_items.append(
                OrderItem(
                    name=name,
                    quantity=quantity,
                    unit_price=unit_price,
                )
            )

        if subtotal > Decimal('99999999.99'):
            messages.error(request, 'Your order total is too large to process.')
            return redirect('cart')

        delivery_charge = Decimal('0.00')
        distance = None
        if fulfillment == Order.Fulfillment.DELIVERY:
            try:
                distance_km = get_driving_distance_km(
                    float(latitude),
                    float(longitude),
                )
            except requests.RequestException:
                logger.exception('Delivery route lookup failed while placing an order.')
                messages.error(
                    request,
                    'We could not verify the delivery route. Please try again.',
                )
                return redirect(checkout_url)
            except (RuntimeError, ValueError):
                logger.exception(
                    'Delivery route could not be verified while placing an order.'
                )
                messages.error(
                    request,
                    'We could not verify the delivery route. Please select your location and try again.',
                )
                return redirect(checkout_url)

            delivery_charge = Decimal(
                str(calculate_delivery_charge(distance_km))
            ).quantize(Decimal('0.01'))
            distance = Decimal(str(distance_km)).quantize(Decimal('0.01'))

        with transaction.atomic():
            order = Order.objects.create(
                customer=request.user,
                customer_name=full_name,
                mobile=mobile,
                fulfillment=fulfillment,
                address=address,
                city=city,
                pincode=pincode,
                landmark=landmark,
                latitude=latitude,
                longitude=longitude,
                delivery_distance_km=distance,
                subtotal=subtotal,
                delivery_charge=delivery_charge,
                total=subtotal + delivery_charge,
                payment_method='cod',
            )
            for item in order_items:
                item.order = order
            OrderItem.objects.bulk_create(order_items)

        return redirect('order_confirmation', order_id=order.pk)

    return render(
        request,
        'customer/checkout.html',
        {
            'fulfillment': fulfillment,
            'google_maps_browser_api_key': getattr(
                django_settings,
                'GOOGLE_MAPS_BROWSER_API_KEY',
                ''
            ),
        }
    )


def order_confirmation(request, order_id):
    if not request.user.is_authenticated:
        return redirect('signin')

    order = get_object_or_404(
        Order.objects.prefetch_related('items'),
        pk=order_id,
        customer=request.user,
    )
    return render(
        request,
        'customer/order_confirmation.html',
        {'order': order},
    )


def calculate_delivery(request):
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'message': 'Please sign in first.'}, status=401)
    if request.method != "POST":
        return JsonResponse({'success': False, 'message': 'Invalid request.'}, status=400)
    address = request.POST.get('address', '').strip()
    city = request.POST.get('city', '').strip()
    pincode = request.POST.get('pincode', '').strip()
    latitude = request.POST.get('latitude', '').strip()
    longitude = request.POST.get('longitude', '').strip()
    if not address:
        return JsonResponse(
            {'success': False, 'message': 'Please enter your house/flat/building number.'},
            status=400,
        )
    if not city:
        return JsonResponse(
            {'success': False, 'message': 'Please select your delivery location.'},
            status=400,
        )
    if not pincode.isdigit() or len(pincode) != 6:
        return JsonResponse(
            {'success': False, 'message': 'Please select a location with a valid 6-digit PIN code.'},
            status=400,
        )
    try:
        customer_latitude = float(latitude)
        customer_longitude = float(longitude)
    except (TypeError, ValueError):
        return JsonResponse(
            {'success': False, 'message': 'Please search for and select your delivery location first.'},
            status=400,
        )
    if not (
        math.isfinite(customer_latitude)
        and math.isfinite(customer_longitude)
        and 6 <= customer_latitude <= 38
        and 68 <= customer_longitude <= 98
    ):
        return JsonResponse({'success': False, 'message': 'The selected delivery location is invalid.'}, status=400)

    try:
        distance_km = get_driving_distance_km(
            customer_latitude,
            customer_longitude,
        )
    except requests.RequestException:
        logger.exception('Google Routes request failed.')
        return JsonResponse(
            {
                'success': False,
                'message': 'Unable to calculate the delivery distance right now. Please try again.',
            },
            status=503,
        )
    except RuntimeError:
        logger.exception('Google Maps server API key is missing.')
        return JsonResponse(
            {
                'success': False,
                'message': 'The delivery service is not configured. Please contact the restaurant.',
            },
            status=503,
        )
    except ValueError:
        logger.exception('Google Routes returned an invalid driving route.')
        return JsonResponse(
            {
                'success': False,
                'message': 'We could not calculate a driving route to this address.',
            },
            status=400,
        )

    return JsonResponse(
        {
            'success': True,
            'distance': round(distance_km, 1),
            'delivery_charge': calculate_delivery_charge(distance_km),
        }
    )


# =========================================================
# SIGN UP
# =========================================================


# =========================================================
# SIGN UP
# =========================================================

def signup(request):

    if request.method == "POST":

        full_name = request.POST.get(
            'full_name',
            ''
        ).strip()

        email = request.POST.get(
            'email',
            ''
        ).strip().lower()

        mobile = request.POST.get(
            'mobile',
            ''
        ).strip()

        password = request.POST.get(
            'password',
            ''
        )

        confirm_password = request.POST.get(
            'confirm_password',
            ''
        )

        if not full_name:

            messages.error(
                request,
                "Please enter your full name."
            )

            return redirect('signup')

        if not email:

            messages.error(
                request,
                "Please enter your email address."
            )

            return redirect('signup')

        if password != confirm_password:

            messages.error(
                request,
                "Passwords do not match."
            )

            return redirect('signup')

        if len(password) < 8:

            messages.error(
                request,
                "Password must be at least 8 characters long."
            )

            return redirect('signup')

        if User.objects.filter(
            email=email
        ).exists():

            messages.error(
                request,
                "Email already registered."
            )

            return redirect('signup')

        if not mobile.isdigit() or len(mobile) != 10:

            messages.error(
                request,
                "Please enter a valid 10-digit mobile number."
            )

            return redirect('signup')

        internal_username = (
            "user_" +
            uuid.uuid4().hex[:20]
        )

        user = User.objects.create_user(
            username=internal_username,
            email=email,
            password=password
        )

        user.first_name = full_name
        user.last_name = mobile

        user.save()

        return redirect('account_created')

    return render(
        request,
        'customer/signup.html'
    )


# =========================================================
# ACCOUNT CREATED
# =========================================================

def account_created(request):

    return render(
        request,
        'customer/account_created.html'
    )


# =========================================================
# LOGIN
# =========================================================

def signin(request):

    if request.method == "POST":
        next_url = request.POST.get('next', '')

        email = request.POST.get(
            'email',
            ''
        ).strip().lower()

        password = request.POST.get(
            'password',
            ''
        )

        try:

            user_by_email = User.objects.get(
                email=email
            )

            user = authenticate(
                request,
                username=user_by_email.username,
                password=password
            )

        except User.DoesNotExist:

            user = None

        if user is not None:

            login(
                request,
                user
            )

            if url_has_allowed_host_and_scheme(
                next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
            ):
                return redirect(next_url)
            return redirect('account')

        else:

            messages.error(
                request,
                "Invalid email or password."
            )

            if next_url:
                return redirect(f"{reverse('signin')}?{urlencode({'next': next_url})}")
            return redirect('signin')

    return render(
        request,
        'customer/signin.html'
    )


# =========================================================
# CUSTOMER ACCOUNT
# =========================================================

def account(request):

    if not request.user.is_authenticated:
        return redirect('signin')

    return render(
        request,
        'customer/account.html'
    )


# =========================================================
# EDIT PROFILE
# =========================================================

def edit_profile(request):

    if not request.user.is_authenticated:
        return redirect('signin')

    user = request.user

    if request.method == "POST":

        full_name = request.POST.get(
            'full_name',
            ''
        ).strip()

        email = request.POST.get(
            'email',
            ''
        ).strip().lower()

        mobile = request.POST.get(
            'mobile',
            ''
        ).strip()

        if not full_name:

            messages.error(
                request,
                "Please enter your full name."
            )

            return redirect('edit_profile')

        if not email:

            messages.error(
                request,
                "Please enter your email address."
            )

            return redirect('edit_profile')

        if not mobile.isdigit() or len(mobile) != 10:

            messages.error(
                request,
                "Please enter a valid 10-digit mobile number."
            )

            return redirect('edit_profile')

        if User.objects.filter(
            email=email
        ).exclude(
            id=user.id
        ).exists():

            messages.error(
                request,
                "This email address is already registered."
            )

            return redirect('edit_profile')

        user.first_name = full_name
        user.email = email
        user.last_name = mobile

        user.save()

        messages.success(
            request,
            "Your profile has been updated successfully."
        )

        return redirect('account')

    return render(
        request,
        'customer/edit_profile.html'
    )


# =========================================================
# CHANGE PASSWORD
# =========================================================

def change_password(request):

    if not request.user.is_authenticated:
        return redirect('signin')

    if request.method == "POST":

        current_password = request.POST.get(
            'current_password',
            ''
        )

        new_password = request.POST.get(
            'new_password',
            ''
        )

        confirm_new_password = request.POST.get(
            'confirm_new_password',
            ''
        )

        if not request.user.check_password(
            current_password
        ):

            messages.error(
                request,
                "Current password is incorrect."
            )

            return redirect('change_password')

        if len(new_password) < 8:

            messages.error(
                request,
                "New password must be at least 8 characters long."
            )

            return redirect('change_password')

        if new_password != confirm_new_password:

            messages.error(
                request,
                "New passwords do not match."
            )

            return redirect('change_password')

        if current_password == new_password:

            messages.error(
                request,
                "New password must be different from your current password."
            )

            return redirect('change_password')

        request.user.set_password(
            new_password
        )

        request.user.save()

        update_session_auth_hash(
            request,
            request.user
        )

        messages.success(
            request,
            "Your password has been changed successfully."
        )

        return redirect('settings')

    return render(
        request,
        'customer/change_password.html'
    )


# =========================================================
# SETTINGS
# =========================================================

def settings(request):

    if not request.user.is_authenticated:
        return redirect('signin')

    return render(
        request,
        'customer/settings.html'
    )


# =========================================================
# LOGOUT
# =========================================================

def signout(request):

    logout(request)

    return redirect('signin')


# =========================================================
# MY ORDERS
# =========================================================

def my_orders(request):

    if not request.user.is_authenticated:
        return redirect('signin')

    orders = Order.objects.filter(
        customer=request.user
    ).prefetch_related('items')

    return render(
        request,
        'customer/my_orders.html',
        {'orders': orders}
    )
