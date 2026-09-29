from django.urls import path
from . import views


urlpatterns = [

    path(
        '',
        views.home,
        name='home'
    ),

    path(
        'menu/',
        views.menu,
        name='menu'
    ),

    path(
        'signup/',
        views.signup,
        name='signup'
    ),

    path(
        'account-created/',
        views.account_created,
        name='account_created'
    ),

    path(
        'signin/',
        views.signin,
        name='signin'
    ),

    path(
        'account/',
        views.account,
        name='account'
    ),

    path(
        'edit-profile/',
        views.edit_profile,
        name='edit_profile'
    ),

    path(
        'change-password/',
        views.change_password,
        name='change_password'
    ),

    path(
        'settings/',
        views.settings,
        name='settings'
    ),

    path(
        'my-orders/',
        views.my_orders,
        name='my_orders'
    ),

    path(
        'signout/',
        views.signout,
        name='signout'
    ),

    path('cart/', 
         views.cart, 
         name='cart'
    ),

    

    path('checkout/', views.checkout, name='checkout'),

    path('order-confirmation/<int:order_id>/', views.order_confirmation, name='order_confirmation'),

    path('address-suggestions/', views.address_suggestions, name='address_suggestions'),

    path('current-location/', views.current_location, name='current_location'),

    path('calculate-delivery/', views.calculate_delivery, name='calculate_delivery'),

    path('hotel-distance/', views.hotel_distance, name='hotel_distance'),

    path('staff/orders/', views.staff_orders, name='staff_orders'),

    path('staff/orders/<int:order_id>/status/', views.update_order_status, name='update_order_status'),
]