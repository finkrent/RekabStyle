# API Reference

Base URL: `/api/v1/`. Most requests and responses use JSON. Custom-design order
creation uses `multipart/form-data`; payment callbacks may redirect the browser.

## Conventions

- Lists use `{ "count", "next", "previous", "results" }` with 20 results per page.
  `GET /best-sellers/` returns an unpaginated array.
- Protected endpoints use `Authorization: Bearer <access>`.
- Refresh tokens rotate in an httpOnly, `SameSite=Strict` cookie named
  `refresh_token` by default, scoped to `/api/v1/accounts/`.
- Money is Toman. DRF serializes Decimal values as strings, such as `"250000"`.
- Customer resources are owner-scoped; another user's resource returns `404`.
- Errors use `{ "detail": "..." }` or DRF field-error objects.

## Authentication

`POST /accounts/request-otp/` is public and accepts
`{ "phone_number": "09123456789" }`. It returns `200` with an expiry, `400`
for invalid input, `429` for cooldown or hourly limits, and `503` for SMS failure.

`POST /accounts/verify-otp/` accepts the phone and OTP. Existing users receive
`access`, `logged_in`, `profile_complete`, and the refresh cookie. New phones
receive `national_id_required: true`; the verified phone is staged in the session.

`POST /accounts/complete-registration/` accepts `{ "national_id": "..." }` in
that same browser session. It returns `200` and creates the user, `400` for an
invalid checksum, and `409` for a duplicate phone or national ID.

`POST /accounts/token/refresh/` accepts `{}` with the cookie or
`{ "refresh": "<token>" }` for clients without cookies. It returns a new access
token and rotated cookie. Invalid tokens return `401` and clear the cookie.

`POST /accounts/logout/` requires Bearer authentication and blacklists the
refresh token.

## Profile and addresses

- `GET|PATCH /accounts/profile/`
- `GET|POST /accounts/addresses/`
- `GET|PATCH|DELETE /accounts/addresses/{id}/`

Profile patches accept `first_name` and `last_name`. A complete profile has a
national ID, both names, and at least one address. Address creation accepts
`{ "address": "...", "postal_code": "1234567890" }`; postal codes must have
exactly ten digits.

## Catalog

Public endpoints are `GET /products/`, `GET /products/{id}/`,
`GET /categories/`, `GET /categories/{id}/`,
`GET /categories/{id}/subcategories/`, `GET /subcategories/`, and
`GET /best-sellers/`. Product filters are `?category=<numeric-id>`,
`?subcategory=<numeric-id>`, and `?search=<text>`; search checks name and
description. Only active products are public.

## Orders

`GET /orders/` is authenticated and returns the customer's orders, or all orders
for staff. `GET /orders/{id}/` returns one owned order; staff also receive
customer details and payment records.

`POST /orders/` requires a complete profile and address. A normal request is:

```json
{"items":[{"product_id":1,"quantity":2}],"address_id":3}
```

`address_id` is optional and defaults to the newest address. Prices and the
shipping address are snapshotted. Custom design requires multipart fields:

| Field | Requirement |
| --- | --- |
| `items` | JSON string of submitted items |
| `address_id` | Optional address ID |
| `custom_design_product_ids` | JSON string, subset of submitted products |
| `custom_design_description` | Required with selection, maximum 2000 characters |
| `images` | One to three JPEG, PNG, or WEBP files, maximum 5 MiB each |

Design fields are all-or-nothing. Images are checked by content, limited to
6000 by 6000 pixels, and re-encoded before storage. Selected items receive the
configured surcharge, 30 percent by default. The response is `201`; invalid
input returns `400`, and a foreign address returns `404`.

Order statuses are `pending`, `paid`, `processing`, `shipped`, `delivered`, and
`cancelled`. Only pending orders can be paid; staff manage later transitions in
Django Admin.

## Payments

`POST /payments/initiate/` requires `{ "order_id": 1 }` for an owned pending
order. It returns `track_id`, `payment_url`, and a Toman `amount` string. Zibal
receives the amount in Rial.

`GET /payments/callback/?trackId=<id>&success=<value>` is called by Zibal. The
backend always verifies server-side and does not trust the query flag. It returns
JSON or redirects to `FRONTEND_PAYMENT_RESULT_URL`.

`POST /payments/verify/` accepts `{ "track_id": "123456789" }`, verifies with
Zibal, checks the exact amount, and completes the payment idempotently. Unknown,
failed, or mismatched payments return `400`.