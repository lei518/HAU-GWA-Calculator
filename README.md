# HAU Grade & GWA Planner

Django + HTMX portfolio project for Holy Angel University College grade
calculation, target-grade planning, and GWA planning.

The grading engine follows the HAU College Grading System Guide supplied
for this project:

Performance Items -> CSA / MEA -> Computed Average -> Transmuted Value
-> Current Grade

## Run locally

    python -m venv .venv
    .venv\Scripts\activate
    pip install -r requirements.txt
    python manage.py migrate
    python manage.py createsuperuser
    python manage.py runserver

Then open http://127.0.0.1:8000/

Run tests with:

    python manage.py test

SQLite is used automatically unless DATABASE_URL is supplied, in which case
the project connects to PostgreSQL.
