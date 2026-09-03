# Configuration Reference

`config/settings.py` loads `.env` from the project root. Copy `.env.example` to
`.env`; never commit real credentials.

## Environment variables

| Variable | Default / requirement | Purpose |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | Required | Django signing key; startup fails without it |
| `DJANGO_DEBUG` | `False` | Development debug mode |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated hosts |
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
| `KAVENEGAR_SENDER` | Empty | Optional sender number |
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
12 MiB. Administrator payment helpers currently print messages rather than
calling Kavenegar.

## Browser security

CORS and CSRF trusted origins are hard-coded to `http://localhost:3000` and
`http://127.0.0.1:3000`; credentials are allowed. Other origins require a
settings change. The refresh cookie is httpOnly, `SameSite=Strict`, scoped to
`/api/v1/accounts/`, and `Secure` when debug is disabled.

## Database and providers

```sql
CREATE DATABASE shop_db;
```

Kavenegar and Zibal are integrated directly with `requests`, without SDKs.
Kavenegar uses `sms/send.json`; Zibal receives Rial while the application stores
Toman and performs conversion only at the gateway boundary. Production callbacks
should use an absolute public HTTPS URL.