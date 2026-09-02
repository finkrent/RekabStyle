# Backend Developer Guide

The complete map of this project for backend developers: architecture, data
model, business logic, external integrations, testing and known limitations.
Companion docs: `README.md` (quick start), `docs/configuration.md`
(env vars, Kavenegar, Zibal), `docs/deployment.md` (production checklist),
`docs/api.md` (endpoint reference), `docs/frontend.md` (SPA integration).

- [1. Architecture overview](#1-architecture-overview)
- [2. Conventions and tooling](#2-conventions-and-tooling)
- [3. Data model reference](#3-data-model-reference)
- [4. Accounts and authentication internals](#4-accounts-and-authentication-internals)
- [5. Orders internals](#5-orders-internals)
- [6. Payments internals](#6-payments-internals)
- [7. Notifications (SMS)](#7-notifications-sms)
- [8. Settings reference](#8-settings-reference)
- [9. Django Admin](#9-django-admin)
- [10. Testing](#10-testing)
- [11. Security model and known limitations](#11-security-model-and-known-limitations)
- [12. Maintenance and operations](#12-maintenance-and-operations)

---

## 1. Architecture overview

Django 5 + Django REST Framework on PostgreSQL. A single SPA frontend is
planned for the same domain (see `docs/frontend.md`); the API is browser-first.

```
config/                 project: settings.py (all env-driven), urls.py, wsgi/asgi
accounts/               phone+OTP auth, JWT, profile, addresses
  services/otp.py       OTP business logic (hashing, cooldown, attempts)
  validators.py         Iranian phone normalization, national-ID checksum
products/               catalog: categories, subcategories, products, best sellers
orders/                 order placement (cart-less), order history
  services/orders.py   checkout validation + price snapshotting
payments/               Zibal IPG integration, payment verification
  services/zibal.py    raw Zibal REST client (request/start/verify)
  services/payments.py payment orchestration + order completion
notifications/          SMS only (no models, no views)
  services/sms.py      Kavenegar REST client + all message templates
```

Routing (`config/urls.py`):

| Prefix | App | Style |
| --- | --- | --- |
| `/admin/` | Django admin | — |
| `/api/v1/accounts/` | accounts | Explicit `path()` routes |
| `/api/v1/` | products | DRF `DefaultRouter` (viewsets) |
| `/api/v1/orders/` | orders | `generics.ListCreateAPIView` / `RetrieveAPIView` |
| `/api/v1/payments/` | payments | `APIView`s |
| `/media/` (DEBUG only) | uploads | served by Django in development |

**Layering convention (please keep it):** views are thin — parse input with a
serializer, delegate to a `services/` function, translate service exceptions
(`OtpError`, `OrderError`, `PaymentError`, `ZibalError`, `SmsError`) into HTTP
responses. All business rules live in services, which are plain functions and
therefore easy to test without the HTTP layer.

App dependency direction (enforced by imports):

```
payments -> orders -> accounts
                 \-> products
notifications <- (accounts, payments)   # services only
```

---

## 2. Conventions and tooling

- **Dependency/venv management: `uv`.** Run everything through
  `uv run python manage.py ...`.
- **Configuration is 100% environment-driven.** `config/settings.py` loads
  `.env` via python-dotenv and fails fast (`RuntimeError`) if
  `DJANGO_SECRET_KEY` is missing. Helpers `_env_bool/_env_int/_env_list`
  parse values. Nothing sensitive is hard-coded; see `docs/configuration.md`.
- **No third-party SDKs.** Kavenegar and Zibal are plain `requests` clients
  with explicit timeouts (10 s / 15 s) and logged errors. Only DRF/SimpleJWT/
  corsheaders/dotenv/Pillow come from outside Django.
- **Money is Toman, `DecimalField(..., decimal_places=0)`**, end to end. The
  only Rial conversion happens at the Zibal boundary (section 6).
- **Timezone: `Asia/Tehran`** (`USE_TZ=True`; stored UTC, rendered +03:30).
- **Authentication:** `JWTAuthentication` + (for the admin and the sign-up
  handoff) `SessionAuthentication`; default permission is `AllowAny`, and
  every non-public view declares its own stricter permission — keep that
  pattern when adding views.
- **Pagination:** DRF `PageNumberPagination`, `PAGE_SIZE=20`, on all list
  endpoints except `GET /api/v1/best-sellers/` (plain array, deliberately).
- **Ownership scoping:** every customer queryset filters by
  `user=request.user`, so foreign objects are `404`, never `403` — do not
  leak existence.

## 3. Data model reference

ER sketch (`->` = FK, `<->` = M2M):

```
User 1--* OtpCode
User 1--* Address
User 1--* Order 1--* OrderItem -> Product
                  1--* Payment
Product <-> Category
Product <-> Subcategory -> Category
BestSeller -> Product
```

### accounts

**User** (custom `AbstractUser` with `USERNAME_FIELD = "phone_number"`
and a matching `UserManager`):

| Field | Notes |
| --- | --- |
| `phone_number` | unique, validated/normalized by `normalize_phone_number` to `09XXXXXXXXX` |
| `national_id` | unique, nullable; `validate_national_id` (10 digits + mod-11 checksum, rejects all-same-digit) |
| `first_name`, `last_name` | profile fields; completion = both non-empty AND `national_id` set |
| `is_active` | disabled accounts are rejected at login (403) |

Property `profile_is_complete` gates order placement.

**OtpCode** — one row per issued OTP: `phone_number`, `code_hash`
(`salt$sha256(salt+code)`, salt = `secrets.token_hex(8)`), `created_at`,
`expires_at`, `attempt_count`, `is_used`. Property `is_expired`.
No automatic cleanup (see section 11).

**Address** — `user` FK, `address` (text), `postal_code`, timestamps.
Orders *copy* address text at purchase time, so later edits never change
shipped orders.

### products

**Category** — `name` (unique), `is_active`.
**Subcategory** — `name`, `category` FK (`PROTECT`), `is_active`.
**Product** — `name` (unique), `description` (text), `price` (Toman
decimal), `image` (optional, `products/` upload), `stock` (int, default 0),
`is_active`, `categories` M2M, `subcategories` M2M, timestamps.

Model-level rule `validate_subcategories`: every chosen subcategory's
category must also be in `categories`. Enforced on `clean()` and at save;
the admin form repeats it because M2M values live on the form pre-save.

**BestSeller** — curated showcase, not computed: `product` (one-to-one)
+ `position` (lower shows first). `GET /api/v1/best-sellers/` returns the
ordered product list, hence it bypasses pagination.

Catalog query behavior (`ProductViewSet`, source-verified):
`?search=` matches `name` **and** `description` (icontains);
`?category=<id>` and `?subcategory=<id>` take **numeric primary keys** and
match any of the product's (many) categories/subcategories (`distinct()` is
applied). A non-numeric value currently raises a 500 (known limitation,
section 11); an unknown but numeric id yields an empty list.
Ordering is `-created_at`.

### orders

**Order** — `order_number` (unique, generated in `save()` as
`{YYYYMMDD}-{8 hex uppercase}`, e.g. `20260901-3F9A1C2D`), `user` FK,
`status` (`pending` / `paid` / `cancelled`, default `pending`),
`total_price` (computed, readonly everywhere), `shipping_address` and
`shipping_postal_code` (snapshots copied from the Address at creation),
timestamps.

**OrderItem** — `order` FK, `product` FK, plus the purchase-time snapshot
fields `product_name` and `unit_price`, `quantity` (min 1). Property
`total_price = unit_price * quantity`. No unique constraint on
`(order, product)`: sending the same product twice creates two lines
(known gap, section 11). **Stock is never decremented.**

### payments

**Payment** — `order` FK, `amount` (Toman decimal, snapshot of
`order.total_price`), `status` (`pending` / `success` / `failed`),
`authority` (the Zibal `trackId`, set after a successful `/v1/request`),
`result_code` (last Zibal result int), `paid_at`, timestamps.
One order can have many Payment rows (retries); verification looks up the
latest row by `authority`.

## 4. Accounts and authentication internals

### 4.1 OTP request/verify (`accounts/services/otp.py`)

`request_otp(phone_number)`:

1. Normalize the number (`09XXXXXXXXX`; accepts `+98`, `0098`, `98`, `0`
   prefixes, strips spaces/dashes/parens — `accounts/validators.py`).
2. **Cooldown:** if the newest `OtpCode` for the number is younger than
   `OTP_COOLDOWN_SECONDS`, raise `OtpError(code="cooldown",
   extra={"retry_after": <seconds>})` → HTTP 429.
3. **Hourly cap:** more than `OTP_MAX_REQUESTS_PER_HOUR` rows in the last
   hour → `code="rate_limited"` → 429.
4. Generate a cryptographically random code (`secrets.choice`, length
   `OTP_LENGTH`), store only `salt$sha256(salt+code)`, return
   `(otp, plain_code)`; the *view* sends the SMS.

`verify_otp(phone_number, code)` runs in `transaction.atomic()` with
`select_for_update()` on the newest unused OTP:

- missing → `not_found` (400); expired → `expired` (400);
  `attempt_count >= OTP_MAX_VERIFY_ATTEMPTS` → `too_many_attempts` (429).
- The attempt counter is incremented **inside** the transaction but the
  `invalid` error is raised **after** committing, so failed attempts
  accumulate and the OTP really does lock out.
- Hash comparison uses `secrets.compare_digest` (no timing oracle).
- On success the row is marked `is_used`.

There is **no per-IP throttle** — only per-phone (known limitation).

### 4.2 Sign-in vs sign-up (`accounts/views.py`)

`POST /verify-otp/` decides after verification:

- **Existing phone** → `django.contrib.auth.login(...)` (a real Django
  session is created too — that is what authenticates `/admin/`) **and**
  JWTs are issued: `access` in the JSON body, refresh token in the
  httpOnly cookie. Response includes `profile_complete`.
- **New phone** → no user yet; the verified number is staged in
  `request.session["pending_signup_phone"]` and the response says
  `national_id_required: true`.

`POST /complete-registration/` (guarded by the `HasPendingSignup`
permission on the staged session) creates the user. National-ID uniqueness
is enforced three ways: a cheap pre-check, a re-check inside
`transaction.atomic()`, and the DB unique constraint (`IntegrityError` →
409 `code=conflict`). Both login paths also set the refresh cookie.

### 4.3 JWT cookie design

- Access token (`SIMPLE_JWT.ACCESS_TOKEN_LIFETIME`): short-lived,
  returned in the body only — the frontend keeps it in memory, never in
  storage.
- Refresh token: long-lived, **httpOnly** cookie. All attributes come from
  `settings.JWT_REFRESH_COOKIE` (`NAME/MAX_AGE/PATH/SECURE/HTTPONLY/
  SAMESITE`); `.env.example`/`docs/configuration.md` document the env vars.
  `SECURE` follows `DEBUG` by default (Secure cookie when `DEBUG=False`).
- `POST /token/refresh/` accepts the cookie (or a legacy body `refresh`
  for tools like Postman), **rotates** the refresh token: response sets the
  new cookie, old token is blacklisted (`ROTATE_REFRESH_TOKENS=True`,
  blacklist app enabled). Invalid/missing token → 401 and the cookie is
  cleared.
- `POST /logout/` (authenticated) blacklists the cookie's refresh token and
  clears the cookie. Errors on already-invalid tokens are ignored.
- Both endpoints are deliberately token-based (no `SessionAuthentication`),
  so no CSRF token is needed for them.

### 4.4 Profile and addresses

`ProfileView` (GET/PATCH own user), `AddressListCreateView` +
`AddressDetailView` (CRUD scoped to `user=request.user`; foreign ids 404).

## 5. Orders internals

`POST /api/v1/orders/` (`orders/views.OrderListCreateView` +
`orders/services/orders.create_order`):

1. `OrderCreateSerializer` validates `address_id` (optional) and `items`
   (list of `{product_id, quantity}`; the product must exist and be
   `is_active`, quantity ≥ 1 — failures are plain 400s, including unknown
   product ids).
2. Address resolution: the given `address_id` (404 if not owned by the
   caller) or, by default, the user's most recently created address.
3. `create_order` re-checks the hard rules — profile complete, non-empty
   items, address present — then, in one `transaction.atomic()`:
   - creates the `Order` (number generated in `save()`);
   - **locks each product row** (`select_for_update`) and re-validates
     `is_active`, then writes the `OrderItem` snapshot
     (`product_name`, `unit_price`);
   - sums `total_price` onto the order.
4. The address text/postal code are snapshotted onto the order; later
   address edits never affect placed orders.
5. `OrderError` → 400 `{"detail": ...}`.

Custom-design orders: `POST /api/v1/orders/custom-design/`
(`orders/views.CustomDesignOrderCreateView` +
`orders/services/orders.create_custom_design_order`) accepts
`multipart/form-data` (`items` as a JSON string — multipart has no list
type — plus 1-3 `images`, `description`, optional `address_id`). Every item
is priced at `price × (1 + CUSTOM_DESIGN["SURCHARGE_PERCENT"]/100)` (30% by
default, rounded to whole Toman), and a `CustomDesign` row with
`CustomDesignImage` rows (random UUID paths under `designs/YYYY/MM/`) is
attached to the order. Images are validated by **content** in
`orders/services/design_uploads.validate_and_reencode`: per-file size cap,
full Pillow decode (rejects renamed non-images and polyglots), JPEG/PNG/WEBP
allowlist (SVG/GIF can never pass), a dimension cap against decompression
bombs, and a final Pillow **re-encode** that strips EXIF/metadata and any
bytes appended after the image stream. `JSONParser` is intentionally not
enabled on this view: designs must arrive as real file parts, never as
base64 inside JSON bodies.

Read paths: customers see only their own orders (`OrderSerializer`: items,
`payment_status` from the latest payment, no customer block); staff see all
orders with `AdminOrderSerializer` (adds the customer block). Querysets use
`prefetch_related("items", "payments")`; staff also `select_related("user")`.
Order status changes happen **only in Django Admin** — the API has no
cancel/confirm endpoints. Payments never modify `total_price`.

## 6. Payments internals

### 6.1 Zibal client (`payments/services/zibal.py`)

Hand-rolled REST client per Zibal's official docs (`help.zibal.ir/ipg/`):

| Call | Endpoint | Notes |
| --- | --- | --- |
| `request_payment` | `POST /v1/request` | sends `merchant`, `amount` (**Rial**), `callbackUrl`, `orderId`, optional `mobile`/`nationalCode`; returns the `trackId` |
| `payment_url` | `GET /start/{trackId}` | hosted payment page to redirect to |
| `verify_payment` | `POST /v1/verify` | server-side confirmation; returns a normalized dict |

- **Rial/Toman:** Zibal counts Rial; the project counts Toman.
  `RIAL_PER_TOMAN = 10`, converted in both directions at this boundary
  only.
- Known result codes are mapped to user-facing messages (`RESULTS`; 100 =
  success, 201 = already verified, 202 = not paid, ...). `paid` is
  `result in (100, 201) and status in (1, 2)`.
- Network/JSON failures raise `ZibalError` with a user-facing message and
  are logged; timeout is 15 s.

### 6.2 Flow (`payments/views.py` + `payments/services/payments.py`)

**Initiate** (`POST /payments/initiate/`, authenticated): order must be the
caller's and in `pending` status (already-paid → 400). A `Payment` row is
created *before* calling Zibal; if the request fails the payment is marked
`failed`. On success `authority=trackId` is stored and the response carries
`payment_url` for the redirect. Errors map: `PaymentError` → 400,
`ZibalError` → 502.

**Gateway callback** (`GET /payments/callback/`, `AllowAny`, no auth —
Zibal's server hits it): reads `trackId` (and `success`) from the query
string, runs server-side verification, then **redirects the user's browser**
to `FRONTEND_PAYMENT_RESULT_URL` with `status=paid|failed`,
`order_number` (when the payment is resolvable) and `detail`. If the URL is
unconfigured or verification cannot classify the outcome, a JSON fallback
is returned instead. Callback verification is user-less (Zibal is the
client); the per-user ownership check applies only to the authenticated
verify endpoint.

**Verify** (`POST /payments/verify/`, authenticated): `verify_and_complete_
payment(track_id, user=request.user)` — payments belonging to someone else
return the same "Payment not found" error (no existence leak). Verification
always happens **server-side**; frontend claims are never trusted.

`verify_and_complete_payment` guarantees:

- **Amount match:** Zibal's returned Rial amount must equal
  `payment.amount * 10`; mismatch → payment `failed`, error logged, 400.
- **Idempotency:** an already-`success` payment returns as-is; the final
  transition takes `select_for_update()` and re-checks status, so double
  callbacks (Zibal retries are normal) cannot double-complete.
- **Completion:** payment → `success` + `paid_at`, order → `paid`
  (both in one transaction), then success SMS to customer and admin —
  SMS failures are logged, never raised.

### 6.3 Failure semantics

Failed verification marks only the `Payment` `failed`; the order stays
`pending` and can be paid again (a new Payment row). No automatic
cancellation exists. Money in the DB is always Toman.

## 7. Notifications (SMS)

`notifications` has **no models and no views** — only
`notifications/services/sms.py`, the single module that talks to Kavenegar
(official REST API, plain `requests`, no SDK; 10 s timeout):

- `send_sms(receptor, message)` → `POST /v1/{API-KEY}/sms/send.json`;
  success = `return.status == 200`. Optional `KAVENEGAR_SENDER` line number.
- `send_otp_sms` — multi-line Persian OTP template; expiry minutes derived
  from `OTP["EXPIRE_SECONDS"]`.
- `send_order_paid_sms_to_customer` / `..._to_admin` — payment success
  notices; the admin one is skipped (with a logged warning) when
  `ADMIN_PHONE_NUMBER` is unset.

Failures raise `SmsError` (user-facing message) and are logged. Callers
choose the policy: OTP request surfaces SMS failure as an error; payment
success SMS never blocks completion (`payments` wraps both sends in
try/except). Sending is **synchronous** — latency of the SMS provider is on
the request path (known limitation, section 11).

Message templates are hard-coded Persian strings in `sms.py`; there is no
i18n layer.

## 8. Settings reference

Everything lives in `config/settings.py` and is env-driven (full variable
table: `docs/configuration.md`). Highlights for backend work:

| Group | What it controls |
| --- | --- |
| Core | `DJANGO_SECRET_KEY` (required, fail-fast), `DEBUG`, `ALLOWED_HOSTS`, PostgreSQL via individual `DATABASE_*` env vars (no SQLite fallback) |
| Apps | `rest_framework`, `rest_framework_simplejwt.token_blacklist`, `corsheaders` |
| `REST_FRAMEWORK` | `JWTAuthentication` + `SessionAuthentication`; `AllowAny` default permission (views opt into stricter); `PageNumberPagination` (`PAGE_SIZE=20`) |
| `SIMPLE_JWT` | access 30 min / refresh 30 days, `ROTATE_REFRESH_TOKENS=True`, `BLACKLIST_AFTER_ROTATION=True`, `Bearer` header |
| `JWT_REFRESH_COOKIE` | `NAME/MAX_AGE/PATH/SECURE/HTTPONLY/SAMESITE` for the refresh cookie (`SECURE` defaults to `not DEBUG`) |
| `OTP` | `LENGTH`, `EXPIRE_SECONDS`, `COOLDOWN_SECONDS`, `MAX_REQUESTS_PER_HOUR`, `MAX_VERIFY_ATTEMPTS`, `OTP_DEBUG_RETURN_CODE` (dev-only echo of the code) |
| `ZIBAL` | `MERCHANT`, `BASE_URL` (sandbox override), `CALLBACK_URL` (falls back to reverse of `payment-callback`) |
| Kavenegar | `KAVENEGAR_API_KEY`, `KAVENEGAR_SENDER`, `ADMIN_PHONE_NUMBER` |
| Frontend | `FRONTEND_PAYMENT_RESULT_URL` (callback redirect target), CORS `CORS_ALLOWED_ORIGINS` |
| Static/media | `STATIC_URL/ROOT`, `MEDIA_URL/ROOT`; media served by Django only when `DEBUG` |

`OTP_DEBUG_RETURN_CODE` requires `DEBUG=True` **and** the flag — it returns
the OTP code in the HTTP response so flows can be tested without a phone.

## 9. Django Admin

Staff workflows the admin owns (all models registered; customers are
managed here, not via API):

- **Users** (`accounts.admin`): custom `UserAdmin` fieldsets
  (phone/national ID/personal info/permissions), inline addresses, OTP
  codes read-only (`OtpCodeAdmin` forbids adding; hashes are never shown in
  plain text — there is no way to recover a code).
- **Catalog** (`products.admin`): categories with inline subcategories;
  products with inline price/active editing, `filter_horizontal` M2Ms and a
  form-level `validate_subcategories` check; **BestSeller** is a
  drag-free ordered list — staff type a `position` number (lower first),
  products chosen via autocomplete.
- **Orders** (`orders.admin`): search by order number/phone/national ID,
  status filter, **read-only** money/address fields, `OrderItemInline`
  (snapshot fields read-only) and a `PaymentInline` that cannot be added or
  deleted. **This is where an order is manually set to `cancelled`.**
- **Payments** (`payments.admin`): fully read-only ledger — the source of
  truth is always the Zibal verification result, never manual edits.

Admin auth uses the Django session created at OTP login or `/admin/`'s own
login form. (`LANGUAGE_CODE` is `en-us`; Persian text lives only in the SMS
templates.)

## 10. Testing

`uv run python manage.py test` — 87 tests, all green. No external services:
Kavenegar and Zibal are patched at the service boundary (`unittest.mock`),
so tests never touch the network. Tests live per app
(`accounts/tests.py`, `products/tests.py`, `orders/tests.py`,
`payments/tests.py`).

Coverage by area (approximate distribution):

| Area | What is exercised |
| --- | --- |
| accounts | phone normalization variants, national-ID checksum, OTP request cooldown/hourly cap, verify expiry/attempts/lockout, sign-in vs sign-up branching, complete-registration uniqueness races, profile/addresses permissions, refresh rotation + logout blacklisting |
| products | catalog list/detail, `?search=`/`?category=`/`?subcategory=`, inactive filtering, best-seller ordering, subcategory-belongs-to-category rule |
| orders | creation happy path, profile-incomplete/address/empty/ inactive-product rejections, price + address snapshotting, owner/staff visibility |
| payments | initiate (pending check, Zibal failure marking), verify success/amount-mismatch/ idempotency/ownership, callback redirect vs JSON fallback |
| notifications | SMS success/provider-rejection/unreachable paths |

Conventions when adding tests: use Django `TestCase`, patch service
functions (`@patch("payments.services.payments.request_payment")` style),
assert on response **status and JSON shape**, and cover the negative path
of every service exception you add.

## 11. Security model and known limitations

**What is solid (source-verified):**

- OTP codes: cryptographically random, salted-hash storage only, constant-
  time comparison, per-phone cooldown + hourly cap + attempt lockout, row
  locking to prevent verification races.
- JWT: httpOnly refresh cookie (JS never sees it), rotation with server-side
  blacklist, logout revokes, cookie cleared on every auth failure.
- Money: server-side Zibal verification, exact amount matching, idempotent
  completion under `select_for_update`, prices always snapshotted (client
  can never set a price).
- Ownership: every customer queryset is user-scoped (foreign objects 404);
  payments verify ownership too.
- Secrets and tunables all come from env vars; OTP debug echo requires
  `DEBUG=True` **and** an explicit flag.

**Known limitations / audit backlog** (honest list; fix before scaling):

1. No per-IP throttling on OTP endpoints (only per-phone); no DRF
   throttling anywhere.
2. `?category=`/`?subcategory=` with a non-numeric value raises an
   unhandled `ValueError` → **500**; Zibal `trackId` is used unvalidated in
   some paths (`int(track_id)` can 500).
3. N+1 query in `OrderSerializer.get_payment_status` (per-order payment
   lookup instead of using the prefetched `payments`).
4. `OrderItem` allows duplicate product lines (no unique constraint,
   no merge) and `stock` is never decremented (overselling possible).
5. CORS is hard-coded to `http://localhost:3000` (not env-configurable);
   `CORS_ALLOW_CREDENTIALS`/CSRF trusted origins not wired up.
6. No HSTS / `SECURE_SSL_REDIRECT` / secure browser headers in settings
   (deployment relies on the reverse proxy; see `docs/deployment.md`).
7. SMS sending is synchronous and single-threaded (request-path latency;
   no Celery/queue).
8. `OtpCode` rows are never cleaned up (no celery-beat/cron deletion of
   expired rows); the token blacklist grows unbounded (no
   `flushexpiredtokens` schedule — see deployment doc).
9. No structured logging/monitoring hooks; errors go to stderr via the
   default logging config.
10. No API schema/OpenAPI generation; `docs/api.md` is hand-written.

## 12. Maintenance and operations

- **Run locally:** `uv sync`, copy `.env.example` → `.env`, fill PostgreSQL
  + Kavenegar/Zibal keys, `uv run python manage.py migrate`,
  `uv run python manage.py runserver`.
- **Migrations:** app-per-app (`accounts`, `products`, `orders`,
  `payments`); always `uv run python manage.py makemigrations && migrate`
  after model changes.
- **Superuser:** `uv run python manage.py createsuperuser` (prompts for a
  phone number, not a username).
- **Production:** follow `docs/configuration.md` for every variable and
  `docs/deployment.md` for the checklist (HTTPS mandatory — the refresh
  cookie is `Secure` when `DEBUG=False` — plus gunicorn/static/media
  handling). Note `media/` must be served by the web server, not Django.
- **Zibal sandbox:** point `ZIBAL_BASE_URL` and the test merchant at the
  sandbox to develop payments without real money.
- **Where to add a feature:** serializer (validation) → `services/`
  function (business rules + transactions) → thin view translating service
  exceptions → tests patching the service boundary. Update `docs/api.md`
  and this file in the same change.





