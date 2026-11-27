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

Checkout uses a Google Maps JavaScript API key for the map picker. Configure
`GOOGLE_MAPS_BROWSER_API_KEY` in your environment and enable the Maps JavaScript
API in Google Cloud. Restrict the key to the website's HTTP referrers. The
existing Geoapify integration also needs `GEOAPIFY_API_KEY` for address lookup,
reverse geocoding, and driving-distance quotes.

Submitted orders are saved in Django and shown under **Orders** in `/admin/`.
Create an admin login with `python manage.py createsuperuser`. For Render, run
that command in the service shell and configure a persistent PostgreSQL
`DATABASE_URL`; the default SQLite database on the web service's filesystem is
not durable across deploys.

## Deploy free on Render

1. Create a GitHub repository named `Hotel-Camp-Friends-Corner` and push this project.
2. In Render, choose **New +** and **Blueprint**, then select the GitHub repository.
3. Render reads `render.yaml`, installs dependencies, collects static files, runs migrations, and starts the Django server.
4. Add `GOOGLE_MAPS_BROWSER_API_KEY`, `GEOAPIFY_API_KEY`, and a persistent PostgreSQL `DATABASE_URL` in the Render environment. Keep the generated `SECRET_KEY` private. The deployed site will be available at:
   `https://hotel-camp-friends-corner.onrender.com`

The free web service may sleep when idle.