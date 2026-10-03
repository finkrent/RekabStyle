# API Reference

Base URL: `/api/v1/`. Most requests and responses are JSON. Custom-design order
creation uses `multipart/form-data`; the payment callback may redirect the
browser. `GET /api/v1/` returns a public index of the catalog routes.

## Conventions

### Pagination

Paginated lists return `{ "count", "next", "previous", "results" }` with 20
results per page (`?page=<n>`): `GET /products/`, `GET /categories/`,
`GET /orders/`, and `GET /accounts/addresses/`.

Unpaginated arrays: `GET /subcategories/`, `GET /categories/{id}/subcategories/`,
and `GET /best-sellers/`. Nested arrays (profile `addresses`, order `items`,
design `images`) are never paginated.

### Authentication

Protected endpoints use `Authorization: Bearer <access>`. Access tokens live
30 minutes; refresh tokens live 30 days, rotate on every refresh, and travel in
an httpOnly, `SameSite=Strict` cookie named `refresh_token` by default, scoped
to `/api/v1/accounts/` (Secure when debug is disabled).

### Money

Money is Toman. DRF serializes Decimal values as strings, such as `"250000"`.
Zibal receives Rial only at the gateway boundary (Toman × 10).

### Ownership

Customer resources are owner-scoped; another user's resource returns `404`.
Exception: `POST /payments/verify/` with a foreign track ID returns `400`
(`"Payment not found."`).

### Errors

Errors use `{ "detail": "..." }` or DRF field-error objects such as
`{ "postal_code": ["Postal code must be exactly 10 digits."] }`. OTP and
registration failures add a machine-readable `code` (`cooldown`, `rate_limited`,
`too_many_attempts`, `invalid`, `expired`, `not_found`, `conflict`); a
`cooldown` response also carries `retry_after` seconds.

| Status | Meaning |
| --- | --- |
| `200` | Success |
| `201` | Order, payment session, or address created |
| `204` | Address deleted |
| `400` | Validation or payment failure |
| `401` | Missing, expired, or invalid access/refresh token |
| `403` | Disabled account or missing sign-up session |
| `404` | Missing or foreign resource |
| `409` | Duplicate phone or national ID |
| `429` | OTP cooldown, hourly limit, or attempt limit |
| `502` | Zibal gateway failure |
| `503` | OTP SMS failure |

## Endpoint index

| Method | Path | Auth |
| --- | --- | --- |
| GET | `/api/v1/` | Public |
| POST | `/api/v1/accounts/request-otp/` | Public |
| POST | `/api/v1/accounts/verify-otp/` | Public |
| POST | `/api/v1/accounts/complete-registration/` | Public + sign-up session |
| POST | `/api/v1/accounts/token/refresh/` | Public (cookie or body) |
| POST | `/api/v1/accounts/logout/` | Bearer |
| GET, PATCH | `/api/v1/accounts/profile/` | Bearer |
| GET, POST | `/api/v1/accounts/addresses/` | Bearer |
| GET, PATCH, DELETE | `/api/v1/accounts/addresses/{id}/` | Bearer |
| GET | `/api/v1/products/`, `/api/v1/products/{id}/` | Public |
| GET | `/api/v1/categories/`, `/api/v1/categories/{id}/` | Public |
| GET | `/api/v1/categories/{id}/subcategories/` | Public |
| GET | `/api/v1/subcategories/`, `/api/v1/subcategories/{id}/` | Public |
| GET | `/api/v1/best-sellers/` | Public |
| GET, POST | `/api/v1/orders/` | Bearer |
| GET | `/api/v1/orders/{id}/` | Bearer |
| POST | `/api/v1/payments/initiate/` | Bearer |
| GET | `/api/v1/payments/callback/` | Public (gateway redirect) |
| POST | `/api/v1/payments/verify/` | Bearer |

## Authentication

### POST /accounts/request-otp/

Public. Sends an OTP for sign-in or sign-up (account existence is decided after
verification).

```json
{"phone_number": "09123456789"}
```

Accepted formats normalize to `09XXXXXXXXX`: `09…`, `+989…`, `00989…`, `989…`,
and bare `9…`.

| Status | Response |
| --- | --- |
| `200` | `{"detail": "OTP sent successfully.", "expires_in": 180}` |
| `200` | Debug mode (`DJANGO_DEBUG=True` plus `OTP_DEBUG_RETURN_CODE=True`): `{"detail": "OTP generated in debug mode (SMS skipped).", "expires_in": 180, "debug_code": "123456"}` — never enable in production |
| `400` | `{"phone_number": ["Enter a valid Iranian mobile phone number."]}` |
| `429` | `{"detail": "Please wait before requesting another OTP.", "code": "cooldown", "retry_after": 42}` |
| `429` | `{"detail": "Too many OTP requests. Please try again later.", "code": "rate_limited"}` |
| `503` | `{"detail": "Could not send the OTP SMS. Please try again later."}` — the OTP row is deleted, so the cooldown does not block a retry |

`expires_in` is the configured lifetime in seconds (default 180).

### POST /accounts/verify-otp/

Public.

```json
{"phone_number": "09123456789", "otp": "123456"}
```

`otp` is 4–8 digits.

| Status | Response |
| --- | --- |
| `200` | Existing user: `{"detail": "Logged in successfully.", "logged_in": true, "profile_complete": true, "access": "<jwt>"}` plus the refresh cookie |
| `200` | New phone: `{"detail": "Phone number verified. Please provide your national ID to complete registration.", "national_id_required": true}` — the phone is staged in the session; no user row is created yet |
| `400` | `{"detail": "Invalid OTP code.", "code": "invalid"}`; also `expired` and `not_found`. Malformed input returns field errors (`otp` must be digits) |
| `403` | `{"detail": "This account is disabled."}` |
| `429` | `{"detail": "Too many incorrect attempts. Please request a new OTP.", "code": "too_many_attempts"}` |

### POST /accounts/complete-registration/

Public, but requires the browser session created by `verify-otp` for a
not-yet-registered phone.

```json
{"national_id": "0012345679"}
```

The national ID must be exactly 10 digits with a valid checksum.

| Status | Response |
| --- | --- |
| `200` | `{"detail": "Registration completed. You are now logged in.", "logged_in": true, "profile_complete": false, "access": "<jwt>"}` plus the refresh cookie; the user row is created |
| `400` | `{"national_id": ["Invalid national ID."]}` or `["National ID must be exactly 10 digits."]` |
| `403` | `{"detail": "Verify your phone number with an OTP first."}` — no pending sign-up session |
| `409` | `{"detail": "An account with this national ID already exists. Please sign in with your phone number.", "code": "conflict"}` (or the phone-number variant) |

### POST /accounts/token/refresh/

Public. Reads the refresh cookie automatically, or accepts
`{"refresh": "<token>"}` for clients without cookies.

| Status | Response |
| --- | --- |
| `200` | `{"access": "<jwt>"}`; the rotated refresh token is set as the new cookie and the old one is blacklisted |
| `401` | `{"detail": "<reason>", "code": "token_not_valid"}`; missing token: `{"detail": "Refresh token is missing.", "code": "token_not_valid"}`. The cookie is cleared |

### POST /accounts/logout/

Requires Bearer authentication. Blacklists the refresh token found in the
cookie and clears it.

| Status | Response |
| --- | --- |
| `200` | `{"detail": "Logged out successfully."}` |
| `401` | Missing or invalid access token |

## Profile and addresses

### GET /accounts/profile/

Bearer. Returns `200`:

```json
{
  "phone_number": "09123456789",
  "national_id": "0012345679",
  "first_name": "Ali",
  "last_name": "Rezaei",
  "full_name": "Ali Rezaei",
  "addresses": [
    {"id": 1, "address": "Tehran, Vanak St. 1", "postal_code": "1234567890", "created_at": "…", "updated_at": "…"}
  ],
  "profile_complete": true
}
```

`401` when unauthenticated.

### PATCH /accounts/profile/

Bearer. Accepts `first_name` and `last_name`. `phone_number`, `national_id`,
`addresses`, `full_name`, and `profile_complete` are read-only and ignored.
Returns the updated profile (`200`).

A complete profile — national ID, both names, and at least one address — is
required before checkout; `profile_complete` reports it.

### GET /accounts/addresses/

Bearer. Paginated (`200`) list of the caller's addresses, newest first.

### POST /accounts/addresses/

Bearer.

```json
{"address": "Tehran, Vanak St. 1", "postal_code": "1234567890"}
```

| Status | Response |
| --- | --- |
| `201` | The created address object (see the Profile example for its shape) |
| `400` | `{"postal_code": ["Postal code must be exactly 10 digits."]}` or a missing `address` |
| `401` | Unauthenticated |

### GET|PATCH|DELETE /accounts/addresses/{id}/

Bearer, own addresses only: `200`, `200`, and `204` respectively. A foreign or
unknown address returns `404`.

## Catalog

All catalog endpoints are public (`200` without credentials). Only active
records are exposed; inactive or unknown IDs return `404`.

### GET /products/

Paginated. Filters:

| Parameter | Effect |
| --- | --- |
| `?category=<id>` | Products assigned to that category (a product may belong to several) |
| `?subcategory=<id>` | Products assigned to that subcategory (a product may belong to several) |
| `?q=<text>` | Case-insensitive partial match on name or description |

Search trims surrounding whitespace; a blank `q` equals omitting the parameter.
Filters combine with AND. Submit search on Enter or a search-button action — the
API is not meant to be queried per keystroke.

Product object:

```json
{
  "id": 1,
  "name": "Phone X",
  "slug": "phone-x",
  "description": "…",
  "price": "25000000",
  "image": "http://127.0.0.1:8000/media/products/abc.jpg",
  "categories": [1],
  "category_names": ["Electronics"],
  "subcategories": [2],
  "subcategory_names": ["Mobile Phones"],
  "is_active": true,
  "created_at": "…"
}
```

`image` is an absolute URL or `null`.

### GET /products/{id}/

`200` with one product object; `404` for unknown or inactive products.

### GET /categories/

Paginated, alphabetical by name. Category object:

```json
{
  "id": 1,
  "name": "Electronics",
  "is_active": true,
  "subcategories": [
    {"id": 2, "name": "Mobile Phones", "slug": "mobile-phones", "category": 1, "category_name": "Electronics", "is_active": true}
  ],
  "created_at": "…"
}
```

### GET /categories/{id}/

`200` with one category object (nested subcategories); `404` otherwise.

### GET /categories/{id}/subcategories/

Unpaginated array of the category's active subcategories (subcategory object
shape as nested above); `404` for an unknown or inactive category.

### GET /subcategories/

Unpaginated array of active subcategories; optional `?category=<id>` filter.
Subcategory objects include a `slug`.

### GET /subcategories/{id}/

`200` with one subcategory object (`id`, `name`, `slug`, `category`,
`category_name`, `is_active`) and a `products` array containing that
subcategory's active products. Each product uses the product object shape
described above. The list endpoint does not embed products. Returns `404` for
an unknown or inactive subcategory.

### GET /best-sellers/

Unpaginated array of product objects curated in Django Admin, ordered by
position (lower first; ties break newest first). Inactive products never
appear.

## Orders

All order endpoints require Bearer authentication (`401` otherwise).

### GET /orders/

Paginated, newest first. Customers receive their own orders; staff users
receive every order plus customer and payment fields. Order object:

```json
{
  "id": 10,
  "order_number": "20260915-1A2B3C4D",
  "status": "pending",
  "total_price": "200000",
  "payment_status": "success",
  "items": [
    {
      "id": 1,
      "product": 1,
      "product_name": "Phone X",
      "unit_price": "100000",
      "quantity": 2,
      "surcharge_percent": "30.00",
      "total_price": "200000"
    }
  ],
  "custom_design": null,
  "shipping_address": "Tehran, Vanak St. 1",
  "shipping_postal_code": "1234567890",
  "created_at": "…"
}
```

- `payment_status` is the newest payment's status (`pending`, `success`,
  `failed`) or `null`.
- `custom_design` is `null`, or an object
  `{ "description", "surcharge_percent", "status", "order_items": [ids], "images": [{"position", "image"}], "created_at" }`.
  Design statuses are `pending`, `in_review`, `approved`, `rejected`,
  `completed`; only `pending` is set today.
- Staff responses add `customer_phone_number`, `customer_national_id`,
  `customer_first_name`, `customer_last_name`, and `payments`
  (`id`, `amount`, `status`, `authority`, `paid_at`, `created_at`).

### GET /orders/{id}/

`200` with one order (owner or staff); `404` for another user's order.

### POST /orders/

Requires a complete profile and at least one address. JSON body:

```json
{"items": [{"product_id": 1, "quantity": 2}], "address_id": 3}
```

| Field | Rules |
| --- | --- |
| `items` | Required, at least one entry; `product_id` must reference an active product; `quantity` is 1–99 |
| `address_id` | Optional; defaults to the newest address; a foreign address returns `404` |

Prices and the shipping address are snapshotted at purchase time. Duplicate
lines are not merged and stock is never decremented.

| Status | Response |
| --- | --- |
| `201` | The created order object (staff get the staff shape) |
| `400` | `{"detail": "Please complete your profile before placing an order."}`, `{"detail": "Please add an address before placing an order."}`, `{"detail": "Product 'Phone X' is not available."}`, or field errors under `items` |
| `404` | Foreign `address_id` |

Custom-design checkout uses `multipart/form-data`:

| Field | Requirement |
| --- | --- |
| `items` | JSON string of submitted items |
| `address_id` | Optional address ID |
| `custom_design_product_ids` | JSON string array; a subset of the submitted products |
| `custom_design_description` | Required with a selection; maximum 2000 characters |
| `images` | 1–3 files; JPEG, PNG, or WEBP by content; maximum 5 MiB and 6000 × 6000 pixels each |

Design fields are all-or-nothing: any design field without the complete set
returns `400` with field errors on `custom_design_product_ids`,
`custom_design_description`, or `images`. Images are content-sniffed, fully
decoded, and re-encoded through Pillow before storage under
`media/designs/YYYY/MM/`. Selected items receive the configured surcharge
(30 percent by default), frozen onto the order items. A failed image check
returns `400` with `{"detail": "…"}` and creates no order.

Order statuses: `pending`, `paid`, `processing`, `shipped`, `delivered`,
`cancelled`. Only `pending` orders can be paid; staff manage later transitions
in Django Admin.

## Payments

### POST /payments/initiate/

Bearer.

```json
{"order_id": 1}
```

Creates a pending payment and requests a Zibal session for an owned pending
order.

| Status | Response |
| --- | --- |
| `201` | `{"detail": "Payment initiated. Redirect the customer to payment_url.", "track_id": "123456789", "payment_url": "https://gateway.zibal.ir/start/123456789", "amount": "200000"}` |
| `400` | `{"detail": "order_id is required."}`, `{"detail": "This order has already been paid."}`, or `{"detail": "Orders in status 'processing' cannot be paid."}` |
| `404` | Unknown or foreign order |
| `502` | `{"detail": "…"}` — Zibal unreachable or rejected the request; the payment attempt is stored as `failed` |
| `401` | Unauthenticated |

`amount` is a Toman string; Zibal receives Rial (× 10).

### GET /payments/callback/

Public; Zibal redirects the customer's browser here with
`?trackId=<id>&success=<0|1>`. The flag is never trusted alone: `success=1`
triggers server-side verification against Zibal; any other value reports
failure without contacting the gateway.

| Status | Response |
| --- | --- |
| `400` | `{"detail": "trackId is required."}` |
| `200` | Verified: `{"detail": "Payment verified successfully.", "status": "paid", "order_number": "20260915-1A2B3C4D"}` |
| `200` | Cancelled or failed: `{"detail": "Payment was cancelled or failed.", "status": "failed"}` (plus `order_number` when known) |

When `FRONTEND_PAYMENT_RESULT_URL` is configured, the browser is redirected
there instead with `?status=paid|failed&detail=<text>&order_number=<id>`.

### POST /payments/verify/

Bearer. Lets the frontend confirm payment after returning from the gateway.

```json
{"track_id": "123456789"}
```

| Status | Response |
| --- | --- |
| `200` | `{"detail": "Payment verified successfully.", "order_number": "20260915-1A2B3C4D", "order_status": "paid", "payment_status": "success"}` |
| `400` | `track_id` missing, unknown track ID, a foreign track ID (`"Payment not found."`), a gateway-reported failure, or an amount mismatch (`"Payment amount does not match the order amount."`) |
| `502` | Zibal unreachable or returned an invalid response |
| `401` | Unauthenticated |

Verification always happens server-side: the gateway amount (Rial) must equal
the stored Toman amount × 10. Completion is idempotent — a row lock commits
payment and order status together, a repeated call returns `200` without
contacting Zibal again, and success SMS is sent only once. A failed
verification leaves the order `pending`.

After success, the customer and the administrator receive Kavenegar SMS
(template selection and failure handling are described in
[backend.md](backend.md)); SMS failures are logged and never roll back the
payment.
