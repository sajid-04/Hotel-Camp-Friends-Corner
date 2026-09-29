from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.models import User
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.http import JsonResponse
from django.conf import settings as django_settings
from django.urls import reverse

import json
import uuid
import requests

from .models import Order, OrderItem


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

    if request.method == "POST":

        full_name = request.POST.get('full_name', '').strip()
        mobile = request.POST.get('mobile', '').strip()
        address = request.POST.get('address', '').strip()
        landmark = request.POST.get('landmark', '').strip()
        city = request.POST.get('city', '').strip()
        pincode = request.POST.get('pincode', '').strip()
        payment_method = request.POST.get('payment_method', 'cod').strip()
        latitude = request.POST.get('latitude', '').strip()
        longitude = request.POST.get('longitude', '').strip()
        cart_items_raw = request.POST.get('cart_items', '')

        if not full_name:
            messages.error(request, "Please enter your full name.")
            return redirect('checkout')

        if not mobile.isdigit() or len(mobile) != 10:
            messages.error(request, "Please enter a valid 10-digit mobile number.")
            return redirect('checkout')

        if not address:
            messages.error(request, "Please enter your house/flat/building number.")
            return redirect('checkout')

        if not city or not pincode.isdigit() or len(pincode) != 6:
            messages.error(request, "Please select a delivery location with a valid PIN code.")
            return redirect('checkout')

        try:
            customer_latitude = float(latitude)
            customer_longitude = float(longitude)
        except (TypeError, ValueError):
            messages.error(request, "Please search for and select your delivery location first.")
            return redirect('checkout')

        try:
            cart_items = json.loads(cart_items_raw)
        except (TypeError, ValueError):
            cart_items = []

        parsed_items = []
        subtotal = 0

        for item in cart_items if isinstance(cart_items, list) else []:
            name = str(item.get('name', '')).strip()
            try:
                price = int(round(float(item.get('price', 0))))
                quantity = int(item.get('quantity', 0))
            except (TypeError, ValueError):
                continue

            if not name or price <= 0 or quantity <= 0:
                continue

            parsed_items.append({'name': name, 'price': price, 'quantity': quantity})
            subtotal += price * quantity

        if not parsed_items:
            messages.error(request, "Your cart is empty.")
            return redirect('cart')

        distance_km, error_response = _get_driving_distance_km(customer_latitude, customer_longitude)

        if error_response:
            messages.error(request, "Unable to calculate the delivery distance. Please try again.")
            return redirect('checkout')

        delivery_charge = calculate_delivery_charge(distance_km)

        order = Order.objects.create(
            user=request.user,
            full_name=full_name,
            mobile=mobile,
            address=address,
            landmark=landmark,
            city=city,
            pincode=pincode,
            latitude=customer_latitude,
            longitude=customer_longitude,
            payment_method=payment_method,
            delivery_distance_km=round(distance_km, 1),
            delivery_charge=delivery_charge,
            subtotal=subtotal,
            total=subtotal + delivery_charge,
        )

        OrderItem.objects.bulk_create([
            OrderItem(order=order, name=item['name'], price=item['price'], quantity=item['quantity'])
            for item in parsed_items
        ])

        return redirect('order_confirmation', order_id=order.id)

    return render(request, 'customer/checkout.html')


# =========================================================
# ORDER CONFIRMATION
# =========================================================

def order_confirmation(request, order_id):

    if not request.user.is_authenticated:
        return redirect('signin')

    order = get_object_or_404(Order, id=order_id, user=request.user)

    return render(request, 'customer/order_confirmation.html', {'order': order})


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
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'message': 'Please sign in first.'}, status=401)

    if request.method != "POST":
        return JsonResponse({'success': False, 'message': 'Invalid request.'}, status=400)

    try:
        latitude = float(request.POST.get('latitude', ''))
        longitude = float(request.POST.get('longitude', ''))
    except (TypeError, ValueError):
        return JsonResponse({'success': False, 'message': 'Invalid location coordinates.'}, status=400)

    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return JsonResponse({'success': False, 'message': 'Invalid location coordinates.'}, status=400)

    api_key = getattr(django_settings, 'GEOAPIFY_API_KEY', '')
    if not api_key:
        return JsonResponse({'success': False, 'message': 'Geoapify API key is missing from the running server.'}, status=500)

    try:
        response = requests.get(
            'https://api.geoapify.com/v1/geocode/reverse',
            params={
                'lat': latitude,
                'lon': longitude,
                'format': 'json',
                'apiKey': api_key,
                'limit': 1,
            },
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as error:
        print('Geoapify Reverse Geocoding Error:', error)
        return JsonResponse({'success': False, 'message': 'Unable to find your current location right now. Please try again.'}, status=503)

    results = data.get('results', [])
    if not results:
        return JsonResponse({'success': False, 'message': 'No address could be found for your current location.'}, status=400)

    location = results[0]
    country_code = str(location.get('country_code', '')).lower()
    if country_code and country_code != 'in':
        return JsonResponse({'success': False, 'message': 'Your current location appears to be outside India.'}, status=400)

    city = location.get('city') or location.get('county') or ''
    postcode = str(location.get('postcode') or '').replace(' ', '')
    if not city or not postcode.isdigit() or len(postcode) != 6:
        return JsonResponse({'success': False, 'message': 'We could not determine the city and PIN code from your current location. Please search for your area instead.'}, status=400)

    return JsonResponse({
        'success': True,
        'label': location.get('formatted') or location.get('address_line1') or 'Current Location',
        'city': city,
        'postcode': postcode,
        'state': location.get('state') or 'Karnataka',
        'lat': float(location.get('lat', latitude)),
        'lon': float(location.get('lon', longitude)),
    })


def _get_driving_distance_km(customer_latitude, customer_longitude):
    """Returns (distance_km, error_response); error_response is a JsonResponse when the lookup fails."""

    api_key = getattr(django_settings, 'GEOAPIFY_API_KEY', '')
    if not api_key:
        return None, JsonResponse({'success': False, 'message': 'Geoapify API key is missing from the running server.'}, status=500)

    try:
        route_response = requests.get('https://api.geoapify.com/v1/routing', params={
            'waypoints': f'{RESTAURANT_LATITUDE},{RESTAURANT_LONGITUDE}|{customer_latitude},{customer_longitude}',
            'mode': 'drive', 'type': 'balanced', 'units': 'metric', 'format': 'json', 'apiKey': api_key
        }, timeout=15)
        route_response.raise_for_status()
        route_data = route_response.json()
    except requests.RequestException as error:
        print('Geoapify Routing Error:', error)
        return None, JsonResponse({'success': False, 'message': 'Unable to calculate the delivery distance right now. Please try again.'}, status=503)

    routes = route_data.get('results', [])
    if not routes:
        return None, JsonResponse({'success': False, 'message': 'We could not calculate a driving route to this address.'}, status=400)

    try:
        distance_meters = float(routes[0]['distance'])
    except (KeyError, TypeError, ValueError):
        return None, JsonResponse({'success': False, 'message': 'The delivery distance could not be calculated correctly.'}, status=400)

    return distance_meters / 1000, None


def calculate_delivery(request):
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'message': 'Please sign in first.'}, status=401)
    if request.method != "POST":
        return JsonResponse({'success': False, 'message': 'Invalid request.'}, status=400)
    address=request.POST.get('address','').strip(); city=request.POST.get('city','').strip()
    pincode=request.POST.get('pincode','').strip(); latitude=request.POST.get('latitude','').strip(); longitude=request.POST.get('longitude','').strip()
    if not address: return JsonResponse({'success': False, 'message': 'Please enter your house/flat/building number.'}, status=400)
    if not city: return JsonResponse({'success': False, 'message': 'Please select your delivery location.'}, status=400)
    if not pincode.isdigit() or len(pincode)!=6: return JsonResponse({'success': False, 'message': 'Please select a location with a valid 6-digit PIN code.'}, status=400)
    try: customer_latitude=float(latitude); customer_longitude=float(longitude)
    except (TypeError, ValueError): return JsonResponse({'success': False, 'message': 'Please search for and select your delivery location first.'}, status=400)
    if not (-90 <= customer_latitude <= 90 and -180 <= customer_longitude <= 180):
        return JsonResponse({'success': False, 'message': 'The selected delivery location is invalid.'}, status=400)

    distance_km, error_response = _get_driving_distance_km(customer_latitude, customer_longitude)
    if error_response:
        return error_response

    return JsonResponse({'success':True,'distance':round(distance_km,1),'delivery_charge':calculate_delivery_charge(distance_km)})


# =========================================================
# HOTEL DISTANCE FROM THE CUSTOMER'S CURRENT (LIVE) LOCATION
# =========================================================

def hotel_distance(request):
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'message': 'Please sign in first.'}, status=401)
    if request.method != "POST":
        return JsonResponse({'success': False, 'message': 'Invalid request.'}, status=400)

    try:
        customer_latitude = float(request.POST.get('latitude', ''))
        customer_longitude = float(request.POST.get('longitude', ''))
    except (TypeError, ValueError):
        return JsonResponse({'success': False, 'message': 'Please share your current location first.'}, status=400)

    if not (-90 <= customer_latitude <= 90 and -180 <= customer_longitude <= 180):
        return JsonResponse({'success': False, 'message': 'The detected location is invalid.'}, status=400)

    distance_km, error_response = _get_driving_distance_km(customer_latitude, customer_longitude)
    if error_response:
        return error_response

    return JsonResponse({'success': True, 'distance': round(distance_km, 1), 'delivery_charge': calculate_delivery_charge(distance_km)})


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

    orders = request.user.orders.prefetch_related('items').all()

    return render(
        request,
        'customer/my_orders.html',
        {'orders': orders}
    )


# =========================================================
# STAFF ORDER WORKFLOW
# =========================================================

def staff_orders(request):

    if not request.user.is_authenticated or not request.user.is_staff:
        return redirect('signin')

    status_filter = request.GET.get('status', '').strip()

    orders = Order.objects.select_related('user').prefetch_related('items').all()

    if status_filter in dict(Order.STATUS_CHOICES):
        orders = orders.filter(status=status_filter)

    return render(
        request,
        'customer/staff_orders.html',
        {
            'orders': orders,
            'status_choices': Order.STATUS_CHOICES,
            'status_filter': status_filter,
        }
    )


def update_order_status(request, order_id):

    if not request.user.is_authenticated or not request.user.is_staff:
        return redirect('signin')

    if request.method != "POST":
        return redirect('staff_orders')

    order = get_object_or_404(Order, id=order_id)

    new_status = request.POST.get('status', '').strip()

    if new_status not in dict(Order.STATUS_CHOICES):
        messages.error(request, "Invalid order status.")
    else:
        order.status = new_status
        order.save()
        messages.success(request, f"Order #{order.id} marked as {order.get_status_display()}.")

    status_filter = request.POST.get('status_filter', '').strip()
    redirect_url = reverse('staff_orders')

    if status_filter:
        redirect_url += f"?status={status_filter}"

    return redirect(redirect_url)