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
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

from django.db import transaction
from django.shortcuts import get_object_or_404
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

    api_key = getattr(django_settings, 'GEOAPIFY_API_KEY', '')
    if not api_key:
        raise RuntimeError('Geoapify API key is not configured.')

    response = requests.get(
        'https://api.geoapify.com/v1/routing',
        params={
            'waypoints': (
                f'{RESTAURANT_LATITUDE},{RESTAURANT_LONGITUDE}|'
                f'{latitude},{longitude}'
            ),
            'mode': 'drive',
            'type': 'balanced',
            'units': 'metric',
            'format': 'json',
            'apiKey': api_key,
        },
        timeout=15,
    )
    response.raise_for_status()
    routes = response.json().get('results', [])
    if not routes:
        raise ValueError('No driving route was returned.')

    try:
        distance_meters = float(routes[0]['distance'])
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
        return redirect('signin')

    if request.method == 'POST':
        full_name = request.POST.get('full_name', '').strip()
        mobile = request.POST.get('mobile', '').strip()
        address = request.POST.get('address', '').strip()
        city = request.POST.get('city', '').strip()
        pincode = request.POST.get('pincode', '').strip()
        landmark = request.POST.get('landmark', '').strip()

        if not full_name or len(full_name) > 120:
            messages.error(request, 'Please enter a valid full name.')
            return redirect('checkout')
        if not mobile.isdigit() or len(mobile) != 10:
            messages.error(request, 'Please enter a valid 10-digit mobile number.')
            return redirect('checkout')
        if not address or len(address) > 255:
            messages.error(request, 'Please enter a valid house, flat or building number.')
            return redirect('checkout')
        if not city or len(city) > 100:
            messages.error(request, 'Please select your delivery location.')
            return redirect('checkout')
        if not pincode.isdigit() or len(pincode) != 6:
            messages.error(request, 'Please select a location with a valid 6-digit PIN code.')
            return redirect('checkout')
        if len(landmark) > 255:
            messages.error(request, 'The landmark must be 255 characters or fewer.')
            return redirect('checkout')

        try:
            latitude = Decimal(request.POST.get('latitude', ''))
            longitude = Decimal(request.POST.get('longitude', ''))
        except InvalidOperation:
            messages.error(request, 'Please select your delivery location on the map.')
            return redirect('checkout')

        if (
            not latitude.is_finite()
            or not longitude.is_finite()
            or not Decimal('6') <= latitude <= Decimal('38')
            or not Decimal('68') <= longitude <= Decimal('98')
        ):
            messages.error(request, 'The selected delivery location is invalid.')
            return redirect('checkout')

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
            return redirect('checkout')
        except (RuntimeError, ValueError):
            logger.exception(
                'Delivery route could not be verified while placing an order.'
            )
            messages.error(
                request,
                'We could not verify the delivery route. Please select your location and try again.',
            )
            return redirect('checkout')

        delivery_charge = Decimal(
            str(calculate_delivery_charge(distance_km))
        ).quantize(Decimal('0.01'))
        distance = Decimal(str(distance_km)).quantize(Decimal('0.01'))

        with transaction.atomic():
            order = Order.objects.create(
                customer=request.user,
                customer_name=full_name,
                mobile=mobile,
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


# =========================================================
# AUTOMATIC DELIVERY DISTANCE - GEOAPIFY
# =========================================================


def address_suggestions(request):
    if not request.user.is_authenticated:
        return JsonResponse(
            {
                'success': False,
                'message': 'Please sign in first.'
            },
            status=401
        )

    if request.method != "GET":
        return JsonResponse(
            {
                'success': False,
                'message': 'Invalid request.'
            },
            status=400
        )

    text = request.GET.get('q', '').strip()

    if len(text) < 2:
        return JsonResponse(
            {
                'success': True,
                'suggestions': []
            }
        )

    api_key = getattr(
        django_settings,
        'GEOAPIFY_API_KEY',
        ''
    )

    if not api_key:
        return JsonResponse(
            {
                'success': False,
                'message': 'Geoapify API key is missing from the running server.'
            },
            status=500
        )

    # =========================================================
    # BELAGAVI SEARCH AREA
    # 30 KM AROUND HOTEL CAMP FRIENDS CORNER
    # =========================================================

    # Geoapify allows multiple filters separated by |.
    # Both conditions must match:
    #   1. Location must be inside the 30 km circle.
    #   2. Location must be inside India.
    search_filter = (
        f'circle:{RESTAURANT_LONGITUDE},'
        f'{RESTAURANT_LATITUDE},30000|countrycode:in'
    )

    search_bias = (
        f'proximity:{RESTAURANT_LONGITUDE},'
        f'{RESTAURANT_LATITUDE}'
    )

    suggestions = []

    # =========================================================
    # 1. GEOAPIFY ADDRESS AUTOCOMPLETE
    # =========================================================

    try:
        autocomplete_response = requests.get(
            'https://api.geoapify.com/v1/geocode/autocomplete',
            params={
                'text': text,
                'format': 'json',
                'lang': 'en',
                'apiKey': api_key,
                'filter': search_filter,
                'bias': search_bias,
                'limit': 10
            },
            timeout=10
        )

        autocomplete_response.raise_for_status()
        autocomplete_data = autocomplete_response.json()

        for location in autocomplete_data.get('results', []):
            try:
                latitude = float(location.get('lat'))
                longitude = float(location.get('lon'))
            except (TypeError, ValueError):
                continue

            country_code = str(
                location.get('country_code', '')
            ).lower()

            if country_code != 'in':
                continue

            label = (
                location.get('formatted')
                or location.get('address_line1')
                or location.get('name')
                or location.get('street')
                or text
            )

            city = (
                location.get('city')
                or location.get('county')
                or ''
            )

            street = location.get('street') or ''

            postcode = str(
                location.get('postcode') or ''
            ).replace(' ', '')

            state = (
                location.get('state')
                or 'Karnataka'
            )

            result_type = (
                location.get('result_type')
                or ''
            )

            suggestions.append(
                {
                    'label': label,
                    'city': city,
                    'street': street,
                    'postcode': postcode,
                    'state': state,
                    'lat': latitude,
                    'lon': longitude,
                    'result_type': result_type
                }
            )

    except requests.RequestException as error:
        print(
            'Geoapify Autocomplete Error:',
            error
        )

    # =========================================================
    # 2. FALLBACK - NORMAL GEOCODING SEARCH
    # =========================================================

    if not suggestions:
        try:
            search_response = requests.get(
                'https://api.geoapify.com/v1/geocode/search',
                params={
                    'text': text,
                    'format': 'json',
                    'lang': 'en',
                    'apiKey': api_key,
                    'filter': search_filter,
                    'bias': search_bias,
                    'limit': 10
                },
                timeout=10
            )

            search_response.raise_for_status()
            search_data = search_response.json()

            for location in search_data.get('results', []):
                try:
                    latitude = float(location.get('lat'))
                    longitude = float(location.get('lon'))
                except (TypeError, ValueError):
                    continue

                country_code = str(
                    location.get('country_code', '')
                ).lower()

                if country_code != 'in':
                    continue

                label = (
                    location.get('formatted')
                    or location.get('address_line1')
                    or location.get('name')
                    or location.get('street')
                    or text
                )

                city = (
                    location.get('city')
                    or location.get('county')
                    or ''
                )

                street = location.get('street') or ''

                postcode = str(
                    location.get('postcode') or ''
                ).replace(' ', '')

                state = (
                    location.get('state')
                    or 'Karnataka'
                )

                result_type = (
                    location.get('result_type')
                    or ''
                )

                suggestions.append(
                    {
                        'label': label,
                        'city': city,
                        'street': street,
                        'postcode': postcode,
                        'state': state,
                        'lat': latitude,
                        'lon': longitude,
                        'result_type': result_type
                    }
                )

        except requests.RequestException as error:
            print(
                'Geoapify Geocoding Fallback Error:',
                error
            )

    # =========================================================
    # 3. BETTER RESULT RANKING
    # =========================================================

    search_words = [
        word.lower()
        for word in text.replace(',', ' ').split()
        if len(word) >= 2
    ]

    search_text = text.lower().strip()

    def calculate_result_score(item):
        score = 0

        label = item['label'].lower()
        city = item['city'].lower()
        street = item['street'].lower()
        state = item['state'].lower()

        # Exact complete search phrase in the result.
        if search_text in label:
            score += 100

        # Individual search words.
        for word in search_words:
            if word in label:
                score += 20

            if word in street:
                score += 30

            if word in city:
                score += 25

        # Strongly prefer Belagavi / Belgaum results.
        if (
            'belagavi' in label
            or 'belgaum' in label
            or 'belagavi' in city
            or 'belgaum' in city
        ):
            score += 80

        # Prefer Karnataka results.
        if 'karnataka' in state:
            score += 20

        # Prefer useful address/location result types.
        if item['result_type'] in (
            'street',
            'suburb',
            'district',
            'amenity',
            'building',
            'postcode'
        ):
            score += 10

        return score

    suggestions.sort(
        key=calculate_result_score,
        reverse=True
    )

    # =========================================================
    # 4. REMOVE DUPLICATES
    # =========================================================

    unique_suggestions = []
    seen = set()

    for item in suggestions:
        key = (
            item['label'].lower(),
            round(item['lat'], 6),
            round(item['lon'], 6)
        )

        if key in seen:
            continue

        seen.add(key)
        unique_suggestions.append(item)

    # =========================================================
    # 5. RETURN TOP RESULTS
    # =========================================================

    return JsonResponse(
        {
            'success': True,
            'suggestions': unique_suggestions[:8]
        }
    )


def current_location(request):
    """Reverse-geocode the exact map centre using parallel Geoapify lookups."""
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'message': 'Please sign in first.'}, status=401)

    if request.method != "POST":
        return JsonResponse({'success': False, 'message': 'Invalid request.'}, status=400)

    try:
        latitude = float(request.POST.get('latitude', ''))
        longitude = float(request.POST.get('longitude', ''))
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            return JsonResponse({'success': False, 'message': 'Invalid location coordinates.'}, status=400)

        api_key = getattr(django_settings, 'GEOAPIFY_API_KEY', '')
        if not api_key:
            logger.error('Geoapify API key is missing.')
            return JsonResponse({'success': False, 'message': 'Location service is not configured. Please contact the restaurant.'}, status=503)

        base_params = {
            'lat': latitude, 'lon': longitude, 'format': 'json',
            'lang': 'en', 'apiKey': api_key, 'limit': 5
        }

        street_params = dict(base_params)
        street_params['type'] = 'street'
        general_params = dict(base_params)
        general_params['limit'] = 1

        def reverse_lookup(params):
            response = requests.get(
                'https://api.geoapify.com/v1/geocode/reverse',
                params=params,
                timeout=(4, 10)
            )
            response.raise_for_status()
            return response.json().get('results', [])

        street_results = []
        general_results = []
        # Run both lookups at the same time so one slow request does not
        # unnecessarily delay the other.
        with ThreadPoolExecutor(max_workers=2) as executor:
            street_future = executor.submit(reverse_lookup, street_params)
            general_future = executor.submit(reverse_lookup, general_params)
            try:
                street_results = street_future.result(timeout=15)
            except Exception:
                logger.exception('Geoapify street reverse-geocoding request failed.')
            try:
                general_results = general_future.result(timeout=15)
            except Exception:
                logger.exception('Geoapify general reverse-geocoding request failed.')

        street_candidates = [
            item for item in street_results
            if item.get('street') or item.get('result_type') == 'street'
        ]
        street_location = street_candidates[0] if street_candidates else (street_results[0] if street_results else {})
        general_location = general_results[0] if general_results else {}

        location = dict(general_location)
        for key, value in street_location.items():
            if value not in (None, ''):
                location[key] = value

        if not location:
            return JsonResponse({
                'success': False,
                'message': 'Geoapify did not return an address. Check the API key, API permissions and server logs.'
            }, status=503)

        country_code = str(location.get('country_code') or general_location.get('country_code') or '').lower()
        if country_code and country_code != 'in':
            return JsonResponse({'success': False, 'message': 'Your selected location appears to be outside India.'}, status=400)

        city = (
            general_location.get('city') or general_location.get('town')
            or general_location.get('village') or general_location.get('county')
            or location.get('city') or location.get('county') or ''
        )
        postcode = str(general_location.get('postcode') or location.get('postcode') or '').replace(' ', '')
        if not city or not postcode.isdigit() or len(postcode) != 6:
            return JsonResponse({
                'success': False,
                'message': 'Could not identify the city and six-digit PIN code for this point. Try another nearby point.'
            }, status=400)

        street = street_location.get('street') or location.get('street') or general_location.get('street') or ''
        house_number = street_location.get('housenumber') or general_location.get('housenumber') or ''
        area = (
            general_location.get('suburb') or general_location.get('neighbourhood')
            or general_location.get('district') or general_location.get('county') or ''
        )
        nearby_place = general_location.get('name') or general_location.get('address_line1') or general_location.get('formatted') or ''
        label = ' '.join(part for part in [house_number, street] if part).strip() if street else (nearby_place or 'Street name not available in map data')

        return JsonResponse({
            'success': True, 'label': label, 'street': street,
            'house_number': house_number, 'area': area,
            'nearby_place': nearby_place,
            'result_type': street_location.get('result_type') or general_location.get('result_type') or '',
            'city': city, 'postcode': postcode,
            'state': general_location.get('state') or location.get('state') or 'Karnataka',
            'lat': latitude, 'lon': longitude
        })

    except (TypeError, ValueError):
        return JsonResponse({'success': False, 'message': 'Invalid location coordinates.'}, status=400)
    except Exception:
        logger.exception('Unexpected error in current_location.')
        return JsonResponse({'success': False, 'message': 'Address lookup failed. Please try again.'}, status=503)


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
        logger.exception('Geoapify routing request failed.')
        return JsonResponse(
            {
                'success': False,
                'message': 'Unable to calculate the delivery distance right now. Please try again.',
            },
            status=503,
        )
    except RuntimeError:
        logger.exception('Geoapify API key is missing.')
        return JsonResponse(
            {
                'success': False,
                'message': 'The delivery service is not configured. Please contact the restaurant.',
            },
            status=503,
        )
    except ValueError:
        logger.exception('Geoapify returned an invalid driving route.')
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

            return redirect('account')

        else:

            messages.error(
                request,
                "Invalid email or password."
            )

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
