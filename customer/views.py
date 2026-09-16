from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.http import JsonResponse
from django.conf import settings as django_settings

import uuid
import requests


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

    return render(request, 'customer/checkout.html')


# =========================================================
# AUTOMATIC DELIVERY DISTANCE - GEOAPIFY
# =========================================================

def address_suggestions(request):
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'message': 'Please sign in first.'}, status=401)
    if request.method != "GET":
        return JsonResponse({'success': False, 'message': 'Invalid request.'}, status=400)
    text = request.GET.get('q', '').strip()
    if len(text) < 3:
        return JsonResponse({'success': True, 'suggestions': []})
    api_key = getattr(django_settings, 'GEOAPIFY_API_KEY', '')
    if not api_key:
        return JsonResponse({'success': False, 'message': 'Geoapify API key is missing from the running server.'}, status=500)
    try:
        response = requests.get('https://api.geoapify.com/v1/geocode/autocomplete', params={
            'text': text, 'format': 'json', 'apiKey': api_key,
            'filter': 'countrycode:in',
            'bias': f'proximity:{RESTAURANT_LONGITUDE},{RESTAURANT_LATITUDE}', 'limit': 6
        }, timeout=10)
        response.raise_for_status(); data = response.json()
    except requests.RequestException as error:
        print('Geoapify Autocomplete Error:', error)
        return JsonResponse({'success': False, 'message': 'Unable to search addresses right now. Please try again.'}, status=503)
    suggestions=[]
    for location in data.get('results', []):
        try: lat=float(location.get('lat')); lon=float(location.get('lon'))
        except (TypeError, ValueError): continue
        if str(location.get('country_code','')).lower() not in ('','in'): continue
        suggestions.append({
            'label': location.get('formatted') or location.get('address_line1') or text,
            'city': location.get('city') or location.get('county') or '',
            'postcode': str(location.get('postcode') or ''),
            'state': location.get('state') or 'Karnataka', 'lat': lat, 'lon': lon
        })
    return JsonResponse({'success': True, 'suggestions': suggestions})


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
    api_key=getattr(django_settings,'GEOAPIFY_API_KEY','')
    if not api_key: return JsonResponse({'success': False, 'message': 'Geoapify API key is missing from the running server.'}, status=500)
    try:
        route_response=requests.get('https://api.geoapify.com/v1/routing', params={
            'waypoints': f'{RESTAURANT_LATITUDE},{RESTAURANT_LONGITUDE}|{customer_latitude},{customer_longitude}',
            'mode':'drive','type':'balanced','units':'metric','format':'json','apiKey':api_key
        }, timeout=15)
        route_response.raise_for_status(); route_data=route_response.json()
    except requests.RequestException as error:
        print('Geoapify Routing Error:', error)
        return JsonResponse({'success': False, 'message': 'Unable to calculate the delivery distance right now. Please try again.'}, status=503)
    routes=route_data.get('results',[])
    if not routes: return JsonResponse({'success': False, 'message': 'We could not calculate a driving route to this address.'}, status=400)
    try: distance_meters=float(routes[0]['distance'])
    except (KeyError, TypeError, ValueError): return JsonResponse({'success': False, 'message': 'The delivery distance could not be calculated correctly.'}, status=400)
    distance_km=distance_meters/1000
    return JsonResponse({'success':True,'distance':round(distance_km,1),'delivery_charge':calculate_delivery_charge(distance_km)})


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

    return render(
        request,
        'customer/my_orders.html'
    )