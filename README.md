# Hotel Camp Friends Corner

A Django website for Hotel Camp Friends Corner, including the home page, menu, and account signup flow.

## Run locally

```powershell
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Open `http://127.0.0.1:8000/` in a browser.

## Checkout and orders

Customers choose takeaway or delivery in the cart. Takeaway orders are
collected from the restaurant with no delivery charge; both types require
customer contact details and are identified in the order and admin views.

Delivery checkout uses Google Maps for the map, address search, reverse geocoding and
driving-distance quotes. In Google Cloud, enable Maps JavaScript API, Places
API (New), Geocoding API and Routes API and configure billing. Usage may incur
charges.

Set `GOOGLE_MAPS_BROWSER_API_KEY` to a browser key restricted to the website's
HTTP referrers and the Maps JavaScript, Places (New) and Geocoding APIs. Set
`GOOGLE_MAPS_SERVER_API_KEY` to a separate server-side key restricted to the
Routes API; do not expose this key in browser code. Apply an IP restriction
only if the hosting service has a stable outbound IP. Search results are
restricted to an area around Belagavi; customers confirm the precise pin on
the map. Google may return a nearby address rather than an exact house address.
After a customer confirms the pin, the driving distance and delivery charge
are calculated automatically. The house or building number is optional.

Submitted orders are saved in Django and shown under **Orders** in `/admin/`.
Create an admin login with `python manage.py createsuperuser`. For Render, run
that command in the service shell and configure a persistent PostgreSQL
`DATABASE_URL`; the default SQLite database on the web service's filesystem is
not durable across deploys.

## Hotel dashboard and administration

Run `python manage.py migrate` before starting the updated site. The migrations
populate the existing menu, six special dishes, hotel details and delivery
bands without changing existing orders. Sign in as staff at `/hotel-dashboard/`
for order summaries and links to `/admin/`. The dashboard requires the
`customer.view_order` permission; editing each section additionally requires
the corresponding Django admin permissions. A superuser has all permissions.
Give other staff only the model and inline permissions needed for their work.

In the admin, manage menu items and their variants, category assignments,
availability, and featured details; change hotel contact information, hours,
restaurant coordinates and the special banner; and update order statuses.
Order details are preserved and cannot be deleted through the admin. Featured
images use paths under the project's static files: new photos must be added to
the project and deployed, or durable media storage must be configured before
offering uploads.

Delivery bands specify the inclusive maximum driving distance and charge.
Distances beyond the last band use the separate beyond-band charge; the optional
maximum distance limits delivery coverage. The seeded bands and beyond charge
preserve the existing temporary rates and must be reviewed by the hotel before
production. Takeaway has no delivery charge. Customers must review changed
menu prices or delivery quotes before ordering.

Dashboard date filters use India time. Non-cancelled order value includes
delivery charges and unpaid orders, so it is not confirmed revenue.

## Deploy free on Render

1. Create a GitHub repository named `Hotel-Camp-Friends-Corner` and push this project.
2. In Render, choose **New +** and **Blueprint**, then select the GitHub repository.
3. Render reads `render.yaml`, installs dependencies, collects static files, runs migrations, and starts the Django server.
4. Add `GOOGLE_MAPS_BROWSER_API_KEY`, `GOOGLE_MAPS_SERVER_API_KEY`, and a persistent PostgreSQL `DATABASE_URL` in the Render environment. Keep the generated `SECRET_KEY` private. The deployed site will be available at:
   `https://hotel-camp-friends-corner.onrender.com`

The free web service may sleep when idle.