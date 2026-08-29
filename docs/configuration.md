# Configuration

All sensitive configuration lives in environment variables, loaded from a
`.env` file in the project root by `config/settings.py` (python-dotenv).
Never commit the real `.env`; use `.env.example` as the template.

## Environment variables

| Variable | Required | Description |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | yes | Long random string (`python -c "import secrets; print(secrets.token_urlsafe(64))"`) |
| `DJANGO_DEBUG` | no (default `False`) | `True` only for development |
| `DJANGO_ALLOWED_HOSTS` | yes in production | Comma-separated host names |
| `DATABASE_NAME` | yes | PostgreSQL database name |
| `DATABASE_USER` | yes | PostgreSQL user |
| `DATABASE_PASSWORD` | yes | PostgreSQL password |
| `DATABASE_HOST` | no (default `localhost`) | PostgreSQL host |
| `DATABASE_PORT` | no (default `5432`) | PostgreSQL port |
| `OTP_LENGTH` | no (default `6`) | OTP code length |
| `OTP_EXPIRE_SECONDS` | no (default `180`) | OTP validity period |
| `OTP_COOLDOWN_SECONDS` | no (default `90`) | Delay between OTP requests for the same phone number |
| `OTP_MAX_REQUESTS_PER_HOUR` | no (default `5`) | OTP requests allowed per phone number per hour |
| `OTP_MAX_VERIFY_ATTEMPTS` | no (default `5`) | Wrong attempts allowed per OTP |
| `KAVENEGAR_API_KEY` | yes | Kavenegar API key (from Kavenegar panel) |
| `KAVENEGAR_SENDER` | no | Sender line, if your account requires one |
| `OTP_SMS_MESSAGE` | no | Multi-line OTP SMS template; literal `\\n` becomes a newline, `{code}` and `{expire_minutes}` are substituted |
| `ADMIN_PHONE_NUMBER` | yes | Administrator mobile that receives payment SMS (`09xxxxxxxxx`) |
| `ZIBAL_MERCHANT` | yes | Zibal merchant code; use `zibal` for the sandbox |
| `ZIBAL_BASE_URL` | no (default `https://gateway.zibal.ir`) | Zibal API base URL |
| `ZIBAL_CALLBACK_URL` | yes in production | Absolute URL of `/api/v1/payments/callback/` reachable by the customer browser |
| `FRONTEND_PAYMENT_RESULT_URL` | no | If set, payment callback redirects the browser there (`?status=&order_number=&detail=`) |

## PostgreSQL

```sql
CREATE DATABASE shop_db;
```

The Django test runner needs `CREATE DATABASE` permission for the configured
user. Connection values are read from `DATABASE_*` variables only - nothing is
hard-coded.

## Kavenegar

1. Register at kavenegar.com and get the API key from the panel.
2. OTP codes are sent as plain multi-line SMS via `sms/send.json` - no
   approved template or special Kavenegar plan is required. Customize the
   message through `OTP_SMS_MESSAGE` if needed.

Integration is implemented manually over the REST API in
`notifications/services/sms.py` (endpoint `sms/send.json`) - no SDK is used.

## Zibal

Zibal integration follows the official IPG API documentation
(<https://help.zibal.ir/ipg/>, OpenAPI spec at
`https://api.zibal.ir/static/helpdocs/ipg.json`) and is implemented in
`payments/services/zibal.py` with `requests` - no SDK.

- Sandbox: set `ZIBAL_MERCHANT=zibal` (payments can be completed with Zibal test cards).
- Production: set your real merchant code.
- **Amounts are sent in Rial**, per the official API. The project stores money
  in Toman and converts automatically (Rial = Toman x 10) at request time; the
  gateway-returned Rial amount is compared against the order after conversion.
- The customer's **national ID is sent as `nationalCode`** (optional per the
  docs): Zibal rejects the transaction if the paying card's owner does not
  match the account's national ID.
- `ZIBAL_CALLBACK_URL` must be the public URL of the callback endpoint; Zibal
  redirects the customer's browser there (`?trackId=&success=&status=&orderId=`)
  and the backend then verifies the transaction **server-side** via `POST /v1/verify`
  (success = result `100`; `201` = already verified, treated as idempotent success).
- Payment page: `GET https://gateway.zibal.ir/start/{trackId}`.
- Result codes are documented in the official tables; common ones (102 merchant
  not found, 103/104 inactive/invalid merchant, 105 amount < 1,000 Rial,
  106 invalid callbackUrl, 113 amount over limit, 114 invalid national code,
  202 not paid) are mapped to friendly messages in `zibal.py`.
