# Deployment

## Requirements

- A Linux server (any modest VPS is enough - the stack has no extra infrastructure)
- PostgreSQL
- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- A reverse proxy (nginx/caddy) for TLS termination

## Checklist

1. **Code**: clone the repository on the server.
2. **Environment**: create `.env` from `.env.example` with production values:
   - strong `DJANGO_SECRET_KEY`
   - `DJANGO_DEBUG=False`
   - `DJANGO_ALLOWED_HOSTS=your-domain.com`
   - real `DATABASE_*` credentials
   - real `KAVENEGAR_API_KEY` (plain SMS is used - no approved template needed)
   - real `ZIBAL_MERCHANT` (not the sandbox value `zibal`)
   - `ZIBAL_CALLBACK_URL=https://your-domain.com/api/v1/payments/callback/`
   - administrator `ADMIN_PHONE_NUMBER`
3. **Install & migrate**:

   ```bash
   uv sync
   uv run python manage.py migrate
   uv run python manage.py collectstatic
   uv run python manage.py createsuperuser
   ```

4. **Run the app** with any WSGI server, e.g. gunicorn (installed separately on
   the server, not part of the project dependencies):

   ```bash
   uv run gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 3
   ```

   Keep it alive with systemd.

5. **Reverse proxy**: forward `https://your-domain.com` to `127.0.0.1:8000`,
   serve `/media/` (uploaded product images) and `/static/` from disk.
6. **Verify**: with `DEBUG=False` the settings enforce secure session/CSRF
   cookies; make sure TLS is actually terminated at the proxy.

## Operational notes

- OTP rate limiting/cooldown is stored in PostgreSQL (`accounts_otrcode`); no
  extra services are needed.
- Payment verification is server-side and idempotent; duplicate callbacks are
  safe.
- Payment SMS failures are logged and never block a successful payment.
- Backups: regular `pg_dump` of the database and the `media/` directory.
