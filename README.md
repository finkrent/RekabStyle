# RekabStyle Backend

RekabStyle is an API-first online shop backend built with Django, Django REST
Framework, PostgreSQL, and `uv`. It provides phone-and-OTP authentication,
catalog browsing, cart-less checkout, optional custom-design orders, Zibal
payments, Kavenegar customer SMS, and Django Admin operations.

There is no frontend in this repository. See [docs/frontend.md](docs/frontend.md)
for the integration contract.

## Quick start

Prerequisites: Python 3.12+, PostgreSQL, and [uv](https://docs.astral.sh/uv/).

1. Create a PostgreSQL database: `CREATE DATABASE shop_db;`.
2. Copy `.env.example` to `.env` and set the secret, database, and integration values.
3. Install and initialize:

   ```bash
   uv sync
   uv run python manage.py migrate
   uv run python manage.py createsuperuser
   ```

4. Start the development server:

   ```bash
   uv run python manage.py runserver
   ```

Admin: `http://127.0.0.1:8000/admin/`

API: `http://127.0.0.1:8000/api/v1/`

For local OTP testing, set `DJANGO_DEBUG=True` and
`OTP_DEBUG_RETURN_CODE=True`. The OTP is returned in the response; never enable
this in production.

## Repository map

| Path | Responsibility |
| --- | --- |
| `config/` | Settings and root URL routing |
| `accounts/` | User, OTP, profile, and address workflows |
| `products/` | Categories, subcategories, products, and best sellers |
| `orders/` | Orders, custom designs, image handling, and checkout |
| `payments/` | Zibal requests, verification, and payment orchestration |
| `notifications/` | Kavenegar REST client and SMS templates |
| `docs/` | Integration and operations documentation |

## Behavior at a glance

Checkout requires a national ID, both profile names, and at least one address.
The backend has no cart: clients submit items at checkout. Product names, prices,
quantities, and shipping addresses are snapshotted onto orders.

Custom-design checkout uses `multipart/form-data`, accepts one to three valid
JPEG, PNG, or WEBP images, and applies the configured surcharge. Images are
decoded and re-encoded with Pillow before storage.

Payments are verified server-side with Zibal. Successful verification is
idempotent and marks the payment and order in one transaction. Customer payment
SMS uses Kavenegar. Administrator notifications select a custom-design or normal
template, but the current admin helpers print their messages because their
Kavenegar send calls are disabled.

Money is stored in Toman and serialized by DRF as JSON strings. Zibal receives
Rial only at the gateway boundary.

## Tests

```bash
uv run python manage.py check
uv run python manage.py test
```

Tests patch Zibal and Kavenegar at service boundaries. The test runner creates a
temporary PostgreSQL database, so the database user needs create-database permission.

## Documentation

- [API reference](docs/api.md)
- [Frontend integration guide](docs/frontend.md)
- [Backend architecture](docs/backend.md)
- [Configuration reference](docs/configuration.md)
- [Deployment guide](docs/deployment.md)