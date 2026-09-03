# Backend Architecture

This explanation describes the implemented Django backend. It supports Django
`>=5.1`, Python `>=3.12`, PostgreSQL, and Django REST Framework.

## Components and boundaries

| App | Responsibility |
| --- | --- |
| `accounts` | User, OTP, profile, and address workflows |
| `products` | Catalog and best sellers |
| `orders` | Checkout, snapshots, custom designs, and image validation |
| `payments` | Zibal client and payment orchestration |
| `notifications` | Kavenegar client and SMS templates |
| `config` | Settings and root routes |

Views adapt HTTP requests. Serializers validate input, services own business
rules and transactions, and provider modules isolate external HTTP calls.
Follow `serializer -> service -> model/provider -> response` when adding work.

## Domain behavior

Users authenticate by normalized phone number and OTP. Codes are random, stored
as salted hashes, expired, and protected by cooldown, hourly, and attempt limits.
Existing users receive an access token and refresh cookie. New users complete
registration with a unique valid national ID. Profile completion requires the
national ID, both names, and at least one address.

Orders snapshot product names, prices, quantities, and shipping addresses.
Checkout locks product rows and validates prices server-side. It does not merge
duplicate lines or decrement stock. Custom designs are one-to-one with orders,
link selected items, and store re-encoded Pillow images under `designs/YYYY/MM/`.

## Payment and notification flow

Initiation creates a pending payment and requests a Zibal track ID. Verification
checks the gateway amount in Rial against the stored Toman amount multiplied by
10. A row lock makes completion idempotent; successful payment and order status
are committed together before notifications are attempted.

Customer payment SMS uses Kavenegar. The administrator helper is selected by the
presence of `order.custom_design`: custom orders use
`send_custom_order_paid_sms_to_admin`, and normal orders use
`send_order_paid_sms_to_admin`. Notification failures are logged and do not
change payment state. The admin helpers currently print instead of sending.

## Testing and known gaps

Run `uv run python manage.py test`. Tests use Django `TestCase` and patch Zibal
and Kavenegar boundaries. Current gaps include no per-IP OTP throttling,
synchronous SMS, no stock decrement, unbounded OTP-row growth, no OpenAPI
schema, and no automatic expired-OTP cleanup. Local CORS origins are hard-coded;
production HTTPS and HSTS policy belongs at the deployment boundary.