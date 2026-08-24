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

## Deploy free on Render

1. Create a GitHub repository named `Hotel-Camp-Friends-Corner` and push this project.
2. In Render, choose **New +** and **Blueprint**, then select the GitHub repository.
3. Render reads `render.yaml`, installs dependencies, collects static files, runs migrations, and starts the Django server.
4. Keep the generated `SECRET_KEY` private. The deployed site will be available at:
   `https://hotel-camp-friends-corner.onrender.com`

The free web service may sleep when idle. SQLite is used for local development; for persistent hosted customer data, add a PostgreSQL `DATABASE_URL` environment variable in Render.