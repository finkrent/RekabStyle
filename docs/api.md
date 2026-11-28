# API Reference

Base URL: `/api/v1/`. Most requests and responses are JSON; order creation is
`application/json`. The payment callback may redirect the browser. The
custom-design flow (currently disabled — see [configuration.md](configuration.md))
uses `multipart/form-data` when enabled. `GET /api/v1/` returns a public index
of the catalog routes.

## Conventions

### Pagination

Paginated lists return `{ "count", "next", "previous", "results" }` with 20
results per page (`?page=<n>`): `GET /categories/`, `GET /orders/`, and
`GET /accounts/addresses/`. `GET /products/` is fixed at 8 products per
page and clients cannot override the page size; `next` is the full URL of
the following page (carrying filters such as `?subcategory=` and `?q=`)
and is `null` after the last page. Products are ordered newest first with
the id as tiebreaker, which keeps sequential pages stable.

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
| `409` | Duplicate phone or national ID, or payment initiation already in progress |
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
| GET | `/api/v1/delivery-methods/` | Public |
| GET, POST | `/api/v1/orders/` | Bearer |
| GET, PATCH | `/api/v1/orders/{id}/` | Bearer |
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
{"national_id": "0012345679", "terms_accepted": true}
```

The national ID must be exactly 10 digits with a valid checksum. `terms_accepted`
must be `true`: accepting the Website Rules and Regulations is mandatory at
sign-up. The acceptance is stored as legal evidence together with the rules
version in force at that moment, the national ID, the timestamp, the client IP,
and the user agent, so a later rules change never rewrites what was agreed to.
A missing or `false` flag returns `400` and creates no user.

| Status | Response |
| --- | --- |
| `200` | `{"detail": "Registration completed. You are now logged in.", "logged_in": true, "profile_complete": false, "access": "<jwt>"}` plus the refresh cookie; the user row and its rules-acceptance record are created |
| `400` | `{"national_id": ["Invalid national ID."]}` or `["National ID must be exactly 10 digits."]`; `{"terms_accepted": ["You must accept the Website Rules and Regulations to sign up."]}` when the rules checkbox was not accepted |
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
  "profile_complete": true,
  "terms_acceptance": {"terms_version": "1.0", "accepted_at": "…"}
}
```

`terms_acceptance` is the latest Website Rules and Regulations acceptance
(`null` when the account was created outside the sign-up flow, for example in
Django Admin). Compare `terms_version` with the version you publish to detect
that a customer accepted older rules; the backend keeps the full acceptance
history.

`401` when unauthenticated.

### PATCH /accounts/profile/

Bearer. Accepts `first_name` and `last_name`. `phone_number`, `national_id`,
`addresses`, `full_name`, `profile_complete`, and `terms_acceptance` are
read-only and ignored.
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

All catalog endpoints are public (`200` without credentials). Categories and
subcategories expose only active records — inactive or unknown IDs return
`404`. Products additionally expose inactive records: they appear in lists
with `"is_active": false` (unknown IDs return `404`) so the storefront can
render them as unavailable.

### GET /products/

Paginated with a fixed 8 products per page (`?page=<n>`; follow the `next`
URL, which preserves every filter). Filters:

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
Inactive products remain in the catalog and carry `"is_active": false`; the
same availability field is returned for nested subcategory products and
best-seller products. The storefront should show them as unavailable and
disable purchase. Checkout rejects inactive products.

When the `subcategory` filter is provided, the paginated response also carries
a top-level `options` array — the active attributes of that subcategory, with
the same option and choice objects as `GET /products/{id}/`. Options belong to
the subcategory and are shared by all its products, so they appear once next to
`results` instead of inside every product. A filter value that matches nothing
(unknown or inactive id) returns `"options": []`. Without the `subcategory`
filter — for example in a plain or search listing — the key is not present.

### GET /products/{id}/

`200` with one product object plus an `options` array (the active
attributes of the product's reference subcategory); `404` for an unknown
product. Inactive products are returned with `"is_active": false`.

The reference subcategory is chosen explicitly with `?subcategory=<id>`
(verified against the product's assignments) or resolved safely: a
product with one subcategory uses it; with several subcategories the only
one that defines active attributes wins; if several define attributes,
`400` `{"subcategory": "…"}` is returned instead of guessing.

Option object inside `options`:

```json
{
  "key": "car_type",
  "label": "نوع خودرو",
  "type": "select",
  "required": true,
  "choices": [
    {"key": "sedan", "label": "سواری", "price_delta": "0"},
    {"key": "offroad", "label": "آفرود", "price_delta": "200000"}
  ]
}
```

Text attributes carry `"type": "text"` and `"price_delta": "0"` instead of
`choices`. The two supported input types are `select` and `text`;
attributes such as `car_type` (select) and `car_model` (text) are defined
once in Django Admin and selected per subcategory (one attribute can be
shared by several subcategories) — the admin enables/disables them, marks
them required, and configures every choice's `price_delta` (Toman).
Inactive attributes — and attributes not selected on the reference
subcategory — never appear. Invalid, foreign, or ambiguous `?subcategory`
values return `400` `{"subcategory": "<reason>"}`.

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
`category_name`, `is_active`), an `options` array, and a `products` array of
that subcategory's products — active and inactive (each carries `is_active`).
Each product uses the product object shape described above. The list endpoint
does not embed products or options. Returns `404` for an unknown or inactive
subcategory.

`options` is a single array of the active attributes selected on the
subcategory — the same shape and choice objects as `GET /products/{id}/`, so a
customer browsing a subcategory gets the option controls (and product list) in
one call without hitting the product detail endpoint per product. Options are a
property of the subcategory shared by all its products, so they appear once
rather than inside every product. Inactive attributes never appear.

Example:

```json
{
  "id": 5,
  "name": "قالپاق",
  "slug": "covers",
  "category": 1,
  "category_name": "خودرو",
  "is_active": true,
  "options": [
    {
      "key": "car_type",
      "label": "نوع خودرو",
      "type": "select",
      "required": true,
      "choices": [
        {"key": "sedan", "label": "سواری", "price_delta": "0"},
        {"key": "offroad", "label": "آفرود", "price_delta": "200000"}
      ]
    }
  ],
  "products": [
    {"id": 12, "name": "قاب X", "slug": "x", "price": "1500000", "is_active": true}
  ]
}
```

### GET /best-sellers/

Unpaginated array of product objects curated in Django Admin, ordered by
position (lower first; ties break newest first). Inactive curated products
appear with `"is_active": false` so the storefront can show them as
unavailable.

## Delivery methods

### GET /delivery-methods/

Public, unpaginated array of the active delivery choices. Each object carries
the stable `code` (send this as `delivery_method` when initiating payment), the
display `name`, and the `price_delta` in Toman:

```json
[
  {"code": "express", "name": "Express delivery", "price_delta": "50000"},
  {"code": "standard", "name": "Standard delivery", "price_delta": "0"}
]
```

Staff configure the choices and their charges under **Delivery methods** in
Django Admin. Order creation does not accept a delivery method. Deactivated
methods disappear from this list and are rejected at payment initiation. The
final order total is always calculated from the backend configuration, never
from a client-supplied amount.

## Orders

All order endpoints require Bearer authentication (`401` otherwise). New order
numbers use `YYYY-MM-DD-XXXXXXXX`, where the suffix is eight uppercase
hexadecimal characters.

### GET /orders/

Paginated, newest first. Customers receive their own orders; staff users
receive every order. Each result is a compact summary containing only these
fields (no items, options, payments, shipping details, or custom design):

```json
{
  "id": 10,
  "order_number": "2026-09-15-1A2B3C4D",
  "status": "pending",
  "total_price": "250000",
  "delivery_method_name": "Express delivery",
  "created_at": "…"
}
```

Superuser results additionally include `"customer_full_name": "Ali Rezaei"`.
Non-superuser staff receive the same summary without customer identity fields.

### GET /orders/{id}/

`200` with one order (owner or staff); `404` for another user's order. Unlike
the list, the detail response contains the full order object:

```json
{
  "id": 10,
  "order_number": "2026-09-15-1A2B3C4D",
  "status": "pending",
  "total_price": "250000",
  "payment_status": "success",
  "items": [
    {
      "id": 1,
      "product": 1,
      "product_name": "Phone X",
      "unit_price": "100000",
      "quantity": 2,
      "surcharge_percent": "30.00",
      "total_price": "200000",
      "options": [
        {
          "attribute_key": "car_type",
          "attribute_label": "نوع خودرو",
          "input_type": "select",
          "choice_key": "offroad",
          "choice_label": "آفرود",
          "text_value": "",
          "price_delta": "200000"
        }
      ]
    }
  ],
  "custom_design": null,
  "shipping_address": "Tehran, Vanak St. 1",
  "shipping_postal_code": "1234567890",
  "delivery_method": "express",
  "delivery_method_name": "Express delivery",
  "delivery_fee": "50000",
  "created_at": "…"
}
```

- `delivery_method` is the saved method code, `delivery_method_name` its
  payment-initiation-time name, and `delivery_fee` the charge added once to the
  order.
  All three are snapshots: renaming, repricing, or deactivating the method
  later never changes existing orders. Orders created before delivery methods
  existed report an empty code/name and a `0` fee.

- `payment_status` is the newest payment's status (`pending`, `success`,
  `failed`) or `null`.
- `options` on each item is an array of immutable purchase-time option
  snapshots (`attribute_key`, `attribute_label`, `input_type`, `choice_key`,
  `choice_label`, `text_value`, `price_delta`; `choice_key`/`choice_label`
  are empty for text options) or `[]`. Attributes and choices are identified
  by their stable keys — ids are not part of the API. Historical orders keep
  these values even after the current attribute/choice definitions are
  edited or deactivated.
- `custom_design` is `null`, or an object
  `{ "description", "surcharge_percent", "status", "order_items": [ids], "images": [{"position", "image"}], "created_at" }`.
  Design statuses are `pending`, `in_review`, `approved`, `rejected`,
  `completed`; only `pending` is set today. While the custom-design intake is
  disabled (`CUSTOM_DESIGN_ENABLED=False`), newly placed orders always return
  `null` here; the object appears only on historical orders.
- Staff detail responses add `customer_phone_number`, `customer_national_id`,
  `customer_first_name`, `customer_last_name`, and `payments`
  (`id`, `amount`, `status`, `authority`, `paid_at`, `created_at`,
  `needs_reconciliation`).

### PATCH /orders/{id}/

Cart-sync replacement: `{"items": [...]}` (same item shape as
`POST /orders/`, including optional `subcategory_id` and
`selected_options`) replaces the order's entire item list — include an
item to add it or change its quantity, omit it to remove it. An empty list
(`{"items": []}`) removes every item without deleting the order. The response
keeps the same order ID, order number, and `pending` status, and returns
`"items": []`; another PATCH can add products to that same order later.

Only `pending` orders without a custom design or a pending payment attempt can
be edited, including when the submitted list is empty; `200` returns the
updated order and `400` reports the reason, in which case the order is left
unchanged. The saved `delivery_fee` and delivery-method snapshots are kept
as-is. Totals are always recalculated as item totals plus that fee, so an empty
order's `total_price` equals its saved `delivery_fee` (zero when no fee was
selected). `PUT /orders/{id}/` is not supported and returns `405`.

### POST /orders/

Requires a complete profile and at least one address. JSON body:

```json
{
  "items": [
    {
      "product_id": 15,
      "quantity": 1,
      "subcategory_id": 2,
      "selected_options": [
        {"option_key": "car_type", "choice_key": "offroad"},
        {"option_key": "car_model", "value": "پژو ۲۰۷"}
      ]
    }
  ],
  "address_id": 3
}
```

Order creation does not require a delivery method. At this stage `total_price`
is the item subtotal and `delivery_fee` is `0`; delivery is selected when
payment is initiated.

| Field | Rules |
| --- | --- |
| `items` | Required, at least one entry; `product_id` must reference an active product; `quantity` is 1–99 |
| `items[].subcategory_id` | Optional reference subcategory (must be one the product belongs to). Options can only be submitted for it; when omitted it is resolved safely — the product's only subcategory, or the only one that defines active attributes |
| `items[].selected_options` | Optional list of `{"option_key": "<attribute key from the product detail options>", "choice_key": "<choice key>"}` for `select` attributes, or `{"option_key": "<attribute key>", "value": "<text>"}` for `text` attributes (non-empty, at most 200 characters). Attributes and choices are addressed by their stable keys, never ids |
| `address_id` | Optional; defaults to the newest address; a foreign address returns `404` |

Unlike PATCH replacement, order creation does not accept an empty `items` list:
`POST /orders/` with `{"items": []}` returns `400` and creates no order.

Option validation is fully generic (nothing is hardcoded per attribute
key): every active required attribute of the reference subcategory must be
submitted and optional ones may be omitted; attributes must be active and
belong to the reference subcategory; choices must belong to the submitted
attribute; `select` attributes reject text values, `text` attributes
reject choice keys; duplicate submissions for one attribute, unknown
fields (including client-supplied prices), and invalid types are
rejected. Client-supplied prices are never trusted.

Pricing is backend-only:
`unit_price = product base price + sum(selected choices' price_delta)`,
`item total = unit price × quantity`. Order creation saves the item subtotal;
payment initiation adds the selected delivery method's `price_delta` once.
The custom-design surcharge multiplies the item price when applied. Deltas are
read from the database at creation time. Every selected option is saved as an
immutable snapshot on the order item (see the order object above), and payment
initiation charges the calculated order total. Prices and the shipping address
are snapshotted at purchase time; delivery is snapshotted at payment initiation.
Duplicate lines are not merged and stock is never decremented.

| Status | Response |
| --- | --- |
| `201` | The created order object (staff get the staff shape) |
| `400` | `{"detail": "Please complete your profile before placing an order."}`, `{"detail": "Please add an address before placing an order."}`, `{"detail": "Product 'Phone X' is not available."}`, field errors under `items`, or option errors such as `{"selected_options": ["Required attributes missing: Car model."]}`, `{"selected_options": ["Choice 'nope' is not available for attribute 'car_type'."]}`. No order or snapshot rows are created |
| `404` | Foreign `address_id` |

Custom-design checkout uses `multipart/form-data`:

> **Currently disabled.** The custom-design intake is turned off with
> `CUSTOM_DESIGN_ENABLED=False` (see
> [configuration.md](configuration.md)). The backend drops these fields
> from the contract: they are neither validated nor priced, and stale
> clients that still send them get a normal `201`. The response field
> `custom_design` remains, so historical orders with designs keep
> rendering. Re-enable with `CUSTOM_DESIGN_ENABLED=True` — the contract
> below becomes active again.

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

Order statuses: `pending`, `paid`, `failed`, `processing`, `shipped`,
`delivered`, `cancelled`. Only `pending` orders containing at least one item can
be paid; staff manage later transitions in Django Admin.

Order deletion is not exposed through this API. In Django Admin, superusers can
delete orders and their item-option snapshots; protected relations, including
payments, can still prevent deletion.

## Payments

### POST /payments/initiate/

Bearer.

```json
{"order_id": 1, "delivery_method": "express"}
```

Creates a pending payment and requests a Zibal session for an owned pending
order that contains at least one item. `delivery_method` is required and must
be an active method from `GET /delivery-methods/`; its configured fee is added
once to the order total and saved with the method snapshot before the gateway
is called.

An empty order returns `400` before a payment is created or an existing session
is recovered; no gateway request is made and any existing pending payment is
left unchanged. This guard also applies when the order has a non-zero saved
delivery fee.

For a non-empty order, an existing authorized pending attempt is recovered:
the response is `200` with the original `track_id` and amount, and with
`"resumed": true`; delivery and the amount are not recalculated and Zibal is
not called again. A new session returns `201` with `"resumed": false`. A recent
pending row without a track ID means initiation is still in progress and
returns `409`; a stale untracked row is marked failed and retried.

| Status | Response |
| --- | --- |
| `200` | Recovered: `{"detail": "Payment session recovered. Redirect to payment_url.", "track_id": "123456789", "payment_url": "https://gateway.zibal.ir/start/123456789", "amount": "200000", "resumed": true}` |
| `201` | Created: `{"detail": "Payment initiated. Redirect the customer to payment_url.", "track_id": "123456789", "payment_url": "https://gateway.zibal.ir/start/123456789", "amount": "200000", "resumed": false}` |
| `400` | `{"order_id": ["This field is required."]}`, `{"delivery_method": ["Choose a delivery method."]}`, `{"delivery_method": ["This delivery method is not available."]}`, `{"detail": "An order must contain at least one item."}`, `{"detail": "This order has already been paid."}`, or `{"detail": "Orders in status 'processing' cannot be paid."}` |
| `409` | `{"detail": "A payment session is being created. Please retry shortly."}` |
| `404` | Unknown or foreign order |
| `502` | `{"detail": "…"}` — Zibal unreachable or rejected the request; the new payment attempt is stored as `failed` |
| `401` | Unauthenticated |

`amount` is the final item-plus-delivery total in Toman; Zibal receives Rial
(× 10). The customer's mobile number and national ID are always sent as Zibal's
`mobile` and `nationalCode` fields. Zibal uses them to load the customer's cards
and check card ownership; it can reject payment when the card's national code
does not match the account's national ID.

### GET /payments/callback/

Public; Zibal redirects the customer's browser here with
`?trackId=<id>&success=<0|1>`. The flag is never trusted alone: both success
and failure callbacks trigger server-side verification against Zibal.

| Status | Response |
| --- | --- |
| `400` | `{"detail": "trackId is required."}` |
| `200` | Verified: `{"detail": "Payment verified successfully.", "status": "paid", "order_number": "2026-09-15-1A2B3C4D"}` |
| `200` | Failed: `{"detail": "…", "status": "failed"}` (plus `order_number` when known); when Zibal confirms failure, the payment and pending order are marked `failed` |

When `FRONTEND_PAYMENT_RESULT_URL` is configured, the browser is redirected
there instead with `?status=paid|failed&detail=<text>&order_number=<id>`.

### POST /payments/verify/

Bearer. Lets the frontend confirm payment after returning from the gateway.

```json
{"track_id": "123456789"}
```

| Status | Response |
| --- | --- |
| `200` | `{"detail": "Payment verified successfully.", "order_number": "2026-09-15-1A2B3C4D", "order_status": "paid", "payment_status": "success"}` |
| `400` | `track_id` missing, unknown track ID, a foreign track ID (`"Payment not found."`), a gateway-reported failure, or an amount mismatch (`"Payment amount does not match the order amount."`) |
| `502` | Zibal unreachable or returned an invalid response |
| `401` | Unauthenticated |

Verification always happens server-side: the gateway amount (Rial) must equal
the stored Toman amount × 10. Completion is idempotent — a row lock commits
payment and order status together, a repeated call returns `200` without
contacting Zibal again, and success SMS is sent only once. A gateway-confirmed
failed payment or amount mismatch marks both the payment and pending order
`failed`. Amount mismatches also set `needs_reconciliation`.

An additional gateway-confirmed charge for an already paid or closed order is
flagged `needs_reconciliation`, is not recorded as another successful payment,
and does not send another order-paid SMS. Staff can review the flag in payment
summaries and Django Admin; reconciliation and refunds are manual.

After success, the customer and the administrator receive Kavenegar SMS
(template selection and failure handling are described in
[backend.md](backend.md)); SMS failures are logged and never roll back the
payment.
