# Deployment Guide

Deploy on Linux with PostgreSQL, a Python WSGI server, and a reverse proxy.
The project does not include Docker, Redis, Celery, or Gunicorn as a dependency.

## Deploy

1. Install Python 3.12+, PostgreSQL, `uv`, and a TLS-terminating proxy.
2. Create a production `.env` with a strong secret, `DJANGO_DEBUG=False`,
   production hosts, database credentials, the real Zibal merchant, and the
   Kavenegar key. Set a public `ZIBAL_CALLBACK_URL`.
3. Initialize the application:

   ```bash
   uv sync
   uv run python manage.py migrate
   uv run python manage.py collectstatic
   uv run python manage.py createsuperuser
   ```

4. Install a WSGI server separately and run, for example:

   ```bash
   uv run gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 3
   ```

5. Proxy HTTPS traffic to Django. Serve `/static/` from `STATIC_ROOT` and
   `/media/` from `MEDIA_ROOT`, including `media/designs/` custom-design images.
6. Forward `X-Forwarded-Proto`. With debug disabled, Django secures session,
   CSRF, and refresh cookies.

## Verify and maintain

Test OTP, profile completion, order creation, payment verification, callback
redirects, and Admin login. Keep database and `media/` backups together because
orders reference uploaded files. Payment verification is server-side and
idempotent; SMS failures do not roll back a successful payment.

Customer payment SMS uses Kavenegar. Administrator helpers currently print their
selected messages. The optional `ADMIN_PHONE_NUMBER` is not required at runtime.

Schedule expired-token cleanup:

```bash
uv run python manage.py flushexpiredtokens
```

Expired `OtpCode` rows have no automatic cleanup, so add a periodic database
cleanup policy. Monitor logs, failed payments, database growth, and media health.