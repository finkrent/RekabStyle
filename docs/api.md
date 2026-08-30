# API Reference

Base URL: `/api/v1/`. All bodies are JSON. Authentication is by **JWT Bearer** token (plus Django session cookies, still
active for the browsable API). See "Authentication" below. Session clients must
send the `X-CSRFToken` header on POST/PATCH; Bearer-token clients do not.

All list endpoints are paginated (`PageNumberPagination`, 20 items per page):
`{ "count", "next", "previous", "results": [...] }`. Use `?page=2` to navigate.

## Authentication

- `verify-otp` (existing user) and `complete-registration` (sign-up) return
  `access` + `refresh` tokens in the response.
- Send the access token as header: `Authorization: Bearer <access>`. Valid 1 day.
- **Postman/API testing:** call `request-otp` -> `verify-otp`, copy `access`,
  set `Authorization: Bearer <access>` on every protected request. No cookies/CSRF needed.
- **Postman without SMS:** with `DJANGO_DEBUG=True` and
  `OTP_DEBUG_RETURN_CODE=True` (set in `.env`), `request-otp` returns the code
  in `debug_code` instead of sending a real SMS. Never enable in production.
- Refresh: `POST /api/v1/accounts/token/refresh/` with `{"refresh": "<refresh>"}`
  returns a new `access`. The refresh token is valid 30 days and is not rotated.

## Accounts

### POST /api/v1/accounts/request-otp/
Public. Rate limited (90s cooldown per phone number + hourly cap). Used for
both sign-in and sign-up.

```json
{ "phone_number": "09123456789" }
```

- `200` `{ "detail": "OTP sent successfully.", "expires_in": 180 }`
- `400` invalid phone number
- `429` cooldown / hourly limit exceeded (`{ "detail", "code", "retry_after" }`)
- `503` SMS provider failure

### POST /api/v1/accounts/verify-otp/
Public.

```json
{ "phone_number": "09123456789", "otp": "123456" }
```

- **Existing phone number** -> the user is logged in and JWT tokens are
  returned:
  `200` `{ "detail", "logged_in": true, "profile_complete": false, "access": "...", "refresh": "..." }`
- **New phone number** -> no user is created yet; the verified phone is staged
  in the session and the client must complete sign-up:
  `200` `{ "detail", "national_id_required": true }`
- `400` invalid / expired / used OTP or no active OTP
- `403` the account exists but is disabled (`is_active=False`)
- `429` too many wrong attempts

### POST /api/v1/accounts/complete-registration/
Public, but requires a session that verified an OTP for a not-yet-registered
phone (`403` otherwise). Required and unique national ID; the user row is
created only after this step succeeds.

```json
{ "national_id": "0012345679" }
```

- `200` `{ "detail", "logged_in": true, "profile_complete": false, "access": "...", "refresh": "..." }` - user
  created and logged in
- `400` invalid national ID (checksum)
- `409` national ID (or phone) already belongs to an account - **no user is
  created**

### GET | PATCH /api/v1/accounts/profile/
Authenticated. `PATCH` accepts `first_name`, `last_name`. `phone_number` and
`national_id` are read-only. The response also includes a read-only
`full_name` and the user's `addresses` (read-only, managed through the
endpoints below).

### Addresses (authenticated, own addresses only)

- `GET /api/v1/accounts/addresses/` - paginated list
- `POST /api/v1/accounts/addresses/` - `{ "address": "...", "postal_code": "1234567890" }`
- `GET | PATCH | DELETE /api/v1/accounts/addresses/{id}/`

A user may store multiple addresses; `400` on invalid postal code (10 digits).
Accessing another user's address returns `404`.

## Catalog (public, paginated)

- `GET /api/v1/products/` - filters: `?category=`, `?subcategory=`, `?search=`
- `GET /api/v1/products/{id}/`
- `GET /api/v1/categories/` - includes nested subcategories
- `GET /api/v1/categories/{id}/`
- `GET /api/v1/categories/{id}/subcategories/`
- `GET /api/v1/subcategories/` - filter: `?category=`
- `GET /api/v1/best-sellers/` - the "Best Sellers" showcase curated by staff
  in Django Admin (not paginated: returns a plain JSON array of product
  objects, ordered by the admin-set position, lower first). Inactive products
  are never exposed; a product can only be added once.

## Orders

### GET /api/v1/orders/
Authenticated. Normal users see only their own orders; staff see all.

### POST /api/v1/orders/
Authenticated. Requires a complete profile (national ID, first name, last name)
and at least one address - otherwise `400`.

```json
{
  "items": [ { "product_id": 1, "quantity": 2 } ],
  "address_id": 3
}
```

`address_id` is optional; when omitted the most recently added address is
used. The chosen address (text + postal code) is **snapshotted onto the order**
at purchase time and later address edits do not affect it.

- `201` order object (order number, status `pending`, items with purchase-time
  prices, shipping address snapshot, total)
- `400` incomplete profile, no address, inactive product
- `404` `address_id` belongs to another user

### GET /api/v1/orders/{id}/
Authenticated. Users can only access their own orders (others get `404`).
Staff responses additionally include customer phone, national ID, first/last
name and payment records; customer responses never include them. Both include
the shipping address snapshot.

### Order status lifecycle

`pending` -> `paid` -> `processing` -> `shipped` -> `delivered`, or
`cancelled`. Only `pending` orders can be paid. Status transitions after
payment are managed by staff through Django Admin; the API never sets them.
Every order object also carries a read-only `payment_status`
(`pending` / `success` / `failed`, from the latest payment attempt; `null`
before any payment was initiated).

## Payments

### POST /api/v1/payments/initiate/
Authenticated, own pending order.

```json
{ "order_id": 1 }
```

- `201` `{ "detail", "track_id", "payment_url", "amount" }` - redirect the
  customer to `payment_url` (Zibal). `amount` is in Toman; Zibal
  internally receives it in Rial (converted automatically).
- `400` order already paid / wrong status; `404` not your order; `502` gateway error

### GET /api/v1/payments/callback/?trackId=...&success=1&status=...
Called by Zibal (browser redirect). Verifies the payment **server-side**, marks
payment + order paid in one transaction, sends SMS to customer and
administrator. Returns JSON or redirects to `FRONTEND_PAYMENT_RESULT_URL`.

### POST /api/v1/payments/verify/
Authenticated, idempotent.

```json
{ "track_id": "123456789" }
```

- `200` `{ "detail", "order_number", "order_status", "payment_status" }`
- `400` unknown track ID, failed payment, amount mismatch

## Error format

DRF default JSON errors (`{ "detail": "..." }` or field errors); no stack
traces or internal details are exposed.
