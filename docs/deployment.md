# Deployment Guide

Deploy on Linux with PostgreSQL, a Python WSGI server, and a reverse proxy.
The project does not include Docker, Redis, or Celery. Gunicorn is included as
the WSGI server dependency.

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

4. Run the WSGI server (Gunicorn is a project dependency; `uv sync` already
   installs it), for example:

   ```bash
   uv run gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 3
   ```

5. Proxy HTTPS traffic to Django. Serve `/static/` from `STATIC_ROOT` and
   `/media/` from `MEDIA_ROOT`, including `media/designs/` custom-design
   images (kept for historical orders; the custom-design intake is disabled
   by default via `CUSTOM_DESIGN_ENABLED=False`).
6. Forward `X-Forwarded-Proto` and `X-Real-IP` from the trusted reverse proxy
   to Gunicorn, and configure the proxy to replace the client-supplied value of
   `X-Real-IP` with the actual remote client address. Gunicorn must expose that
   value to Django as `REMOTE_ADDR`; Django does not read forwarding headers
   directly. This keeps OTP throttles per customer rather than per proxy. With
   debug disabled, Django secures session, CSRF, and refresh cookies.
7. Before accepting payment-initiation requests, configure at least one active
   delivery method in Django Admin under **Delivery methods**. Set its stable
   code, name, price delta in Toman, and active status. Order creation does not
   require a method, but payment initiation requires an active method and
   rejects inactive or unknown codes.

## Verify and maintain

Test OTP, profile completion, order creation, payment verification, callback
redirects, and Admin login. Keep database and `media/` backups together because
orders reference uploaded files. Payment verification is server-side and
idempotent; SMS failures do not roll back a successful payment.

Monitor **Payments** in Django Admin with the **Needs reconciliation** filter.
The flag identifies additional gateway-confirmed charges for already paid or
closed orders and payments whose verified amount does not match the order.
Review and reconcile or refund these manually; the application does not issue
automatic refunds. Additional successful charges do not send another order-paid
SMS.

Customer payment SMS uses Kavenegar. Administrator payment SMS is sent to
`ADMIN_PHONE_NUMBER` when it is configured; unset, it is skipped with a log
warning.

Schedule expired-token cleanup:

```bash
uv run python manage.py flushexpiredtokens
```

Schedule order and OTP cleanup once per day. Order cleanup removes pending
orders with no payment attempts after 24 hours from creation and failed orders
30 days after their last status update. It also deletes their payment records
and custom-design image files; paid orders are never removed. OTP cleanup
removes codes whose `expires_at` timestamp is more than 24 hours old, keeping
recently expired codes available for that retention window. For example, add
these cron entries, replacing the path with the application directory:

```cron
0 3 * * * cd /path/to/mimo-shop && uv run python manage.py cleanup_orders >> /var/log/mimo-shop/order-cleanup.log 2>&1
15 3 * * * cd /path/to/mimo-shop && uv run python manage.py cleanup_otps >> /var/log/mimo-shop/otp-cleanup.log 2>&1
```

Order retention can be overridden for a one-off run with `--pending-hours`
and `--failed-days`. Monitor cleanup logs, failed payments, database growth,
and media health.