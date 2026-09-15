# Configuration Reference

`config/settings.py` loads `.env` from the project root. Copy `.env.example` to
`.env`; never commit real credentials.

## Environment variables

| Variable | Default / requirement | Purpose |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | Required | Django signing key; startup fails without it |
| `DJANGO_DEBUG` | `False` | Development debug mode |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated hosts |
| `DJANGO_CORS_ALLOWED_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | Comma-separated CORS origins |
| `DJANGO_CORS_TRUSTED_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | Comma-separated CSRF trusted origins |
| `DATABASE_NAME` | Required operationally | PostgreSQL database |
| `DATABASE_USER` | Required operationally | PostgreSQL user |
| `DATABASE_PASSWORD` | Required operationally | PostgreSQL password |
| `DATABASE_HOST` | `localhost` | PostgreSQL host |
| `DATABASE_PORT` | `5432` | PostgreSQL port |
| `OTP_LENGTH` | `6` | OTP length |
| `OTP_EXPIRE_SECONDS` | `180` | OTP lifetime |
| `OTP_COOLDOWN_SECONDS` | `90` | Per-phone cooldown |
| `OTP_MAX_REQUESTS_PER_HOUR` | `20` | Per-phone hourly limit |
| `OTP_MAX_VERIFY_ATTEMPTS` | `5` | Failed attempts per OTP |
| `OTP_DEBUG_RETURN_CODE` | `False` | Development-only code echo; requires debug |
| `KAVENEGAR_API_KEY` | Required for real SMS | Kavenegar API key |
| `KAVENEGAR_OTP_TEMPLATE` | `rekab-otp` | Approved OTP lookup template |
| `KAVENEGAR_ORDER_PAID_CUSTOMER_TEMPLATE` | `rekab-order-paid` | Approved order-paid customer template |
| `KAVENEGAR_ORDER_PAID_ADMIN_TEMPLATE` | `rekab-order-paid-admin` | Approved order-paid admin template |
| `KAVENEGAR_CUSTOM_ORDER_PAID_ADMIN_TEMPLATE` | `rekab-custom-order-paid` | Approved custom-order-paid admin template |
| `ADMIN_PHONE_NUMBER` | Empty | Admin notification target; empty skips it |
| `ZIBAL_MERCHANT` | `zibal` | Zibal merchant; `zibal` is sandbox |
| `ZIBAL_BASE_URL` | `https://gateway.zibal.ir` | Zibal API base URL |
| `ZIBAL_CALLBACK_URL` | Empty | Public callback URL; request URL is fallback |
| `FRONTEND_PAYMENT_RESULT_URL` | Empty | Optional payment result redirect |
| `JWT_REFRESH_COOKIE_NAME` | `refresh_token` | Refresh-cookie name |
| `CUSTOM_DESIGN_SURCHARGE_PERCENT` | `30` | Custom-item surcharge |
| `CUSTOM_DESIGN_MAX_IMAGE_BYTES` | `5242880` | Maximum bytes per image |

Fixed custom-design limits are three images, 6000 by 6000 pixels, JPEG/PNG/WEBP
content, and a 2000-character description. Total multipart upload limits are
12 MiB. Administrator payment SMS is sent to ``ADMIN_PHONE_NUMBER`` when it is
configured; unset, it is skipped with a log warning.

## Browser security

CORS and CSRF trusted origins come from `DJANGO_CORS_ALLOWED_ORIGINS` and
`DJANGO_CORS_TRUSTED_ORIGINS`, defaulting to `http://localhost:3000` and
`http://127.0.0.1:3000`; credentials are allowed. The refresh cookie is httpOnly, `SameSite=Strict`, scoped to
`/api/v1/accounts/`, and `Secure` when debug is disabled.

## Database and providers

```sql
CREATE DATABASE shop_db;
```

Kavenegar and Zibal are integrated directly with `requests`, without SDKs.
Kavenegar uses `verify/lookup.json` with panel-approved templates; Zibal receives Rial while the application stores
Toman and performs conversion only at the gateway boundary. Production callbacks
should use an absolute public HTTPS URL.

## Kavenegar templates

All SMS is sent through Kavenegar's `verify/lookup.json`, which can only send
templates created and approved in the Kavenegar panel. Create one template
per message with these placeholders, or point the settings below at your
existing approved templates:

| Template default (setting) | Placeholders |
| --- | --- |
| `rekab-otp` (`KAVENEGAR_OTP_TEMPLATE`) | `%token` = OTP code, `%token2` = expiry in minutes |
| `rekab-order-paid` (`KAVENEGAR_ORDER_PAID_CUSTOMER_TEMPLATE`) | `%token` = order number, `%token2` = total in Toman |
| `rekab-order-paid-admin` (`KAVENEGAR_ORDER_PAID_ADMIN_TEMPLATE`) | `%token` = order number, `%token2` = total in Toman |
| `rekab-custom-order-paid` (`KAVENEGAR_CUSTOM_ORDER_PAID_ADMIN_TEMPLATE`) | `%token` = order number, `%token2` = total in Toman |

Lookup tokens accept only latin letters and digits, so order numbers such as
`20260915-1A2B3C4D` are sent as `202609151A2B3C4D`; amounts are sent as whole
Toman. Until the templates exist in the panel, Kavenegar rejects lookups and
the API surfaces that as an OTP `503` or a logged payment-SMS failure.