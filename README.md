# RekabStyle - Backend

Backend of an online shop built with **Django**, **Django REST Framework**, **PostgreSQL** and **uv**.

- API-first (REST, under `/api/v1/`), no frontend
- Phone number + OTP authentication (no username/password for customers)
- Kavenegar for SMS, Zibal for payments, Django Admin for administration
- Deliberately simple architecture: no Redis, no Celery, no Docker

## Project structure

```text
config/          Project configuration (settings, root URLs, WSGI/ASGI)
accounts/        Custom User (phone number), OTP flow, national ID, profile
products/        Categories, subcategories, products + public catalog APIs
orders/          Orders and order items, checkout business logic
payments/        Zibal payment integration and verification
notifications/   Kavenegar SMS service (isolated service layer)
docs/            Configuration / API / deployment documentation
```

## Quick start

Requires [uv](https://docs.astral.sh/uv/) and PostgreSQL.

```bash
# 1. Create the database (example for psql)
CREATE DATABASE shop_db;

# 2. Configure the environment
cp .env.example .env     # then edit .env with real values (see docs/configuration.md)

# 3. Install dependencies and set up the database
uv sync
uv run python manage.py migrate

# 4. Create the administrator
uv run python manage.py createsuperuser

# 5. Run the development server
uv run python manage.py runserver
```

- Django Admin: http://127.0.0.1:8000/admin/
- API root: http://127.0.0.1:8000/api/v1/

## Running the tests

```bash
uv run python manage.py test
```

The tests mock all external HTTP calls (Kavenegar, Zibal) and use a temporary
PostgreSQL test database (requires `CREATE DATABASE` permission for the DB user).

## Authentication model

Everyone signs in with **phone number + OTP** (plain multi-line SMS). After
verification, an existing phone number logs the user in; a new phone number
requires a **national ID** (required and unique - duplicates are rejected and
no user is created until a valid unused one is provided). Profile details
(first/last name) and **multiple addresses** (text + postal code) are optional
at sign-up but required before checkout; the chosen address is snapshotted
onto each order. Authentication uses **JWT Bearer tokens** (access valid 1 day,
refresh valid 30 days, returned by `verify-otp` / `complete-registration`),
plus Django sessions for the browsable API and Admin. There is no username,
email or password for customers. Staff and superusers log into Django Admin
with a password.

For **Postman / API testing**, send `Authorization: Bearer <access>` on every
protected request (no cookies/CSRF needed). In development you can set
`OTP_DEBUG_RETURN_CODE=True` (with `DJANGO_DEBUG=True`) so `request-otp`
returns the code in `debug_code` instead of sending a real SMS. See
`docs/api.md`.

## Documentation

- `docs/configuration.md` - environment variables, PostgreSQL, Kavenegar, Zibal
- `docs/api.md` - endpoint reference, OTP flow, payment flow
- `docs/deployment.md` - production deployment checklist
