# Frontend Developer Guide

Everything you need to build a web frontend for this shop API — written so you
can follow it whether it is your first API integration or your fiftieth. Read
sections 1–5 once; keep the cheat-sheet (section 9) open while you work.

The backend is Django REST Framework. There is **no official frontend yet** —
the examples below are plain JavaScript with `fetch`, so they work with any
framework (React, Vue, plain HTML). Where a framework matters (React), there is
a note.

---

## 1. The mental model

| Fact | What it means for you |
| --- | --- |
| One base URL: `/api/v1/` | Every endpoint in this document is relative to it, e.g. `/api/v1/products/` |
| JSON in, JSON out | Send `Content-Type: application/json`; every response body is JSON |
| Money is in **Toman** | `price`, `total_price`, `amount` are integers in Toman (the gateway converts to Rial internally — never do this yourself) |
| Timestamps are ISO 8601 | `"created_at": "2026-01-01T10:00:00+03:30"` (Asia/Tehran timezone) |
| Lists are paginated | All list endpoints return `{ "count", "next", "previous", "results": [...] }` with 20 items per page — **except** `GET /best-sellers/`, which returns a plain array |
| Same-domain deployment | In production the SPA and the API are served from **one domain**, so the auth cookie "just works". In development you must use a proxy (section 2.2) |

How authentication looks from your side:

```text
Your SPA                            Django backend
─────────────────────────────       ─────────────────────────────────────
access token  (30 min, in RAM) -->  Authorization: Bearer <access> header
                                    on every protected request

refresh token (30 days)       -->  an httpOnly cookie set by the backend.
JavaScript can never read it.       The browser sends it automatically on
                                    /api/v1/accounts/ requests. You never
                                    touch it — that is the point.
```

Why: if an attacker manages to run XSS on the site, they can steal what is in
JavaScript's reach. The long-lived (30-day) credential is deliberately kept out
of JavaScript's reach; the only thing exposed is a 30-minute access token.

---

## 2. Setting up your development environment

### 2.1 Run the backend

Follow `README.md` ("Quick start"). Then make the `.env` beginner-friendly:

```env
DJANGO_DEBUG=True
OTP_DEBUG_RETURN_CODE=True   # OTP codes come back in the API response, no SMS
ZIBAL_MERCHANT=zibal         # Zibal sandbox
```

Create test data in Django Admin (`http://127.0.0.1:8000/admin/`):
Categories → Subcategories → Products (tick `is_active`) → optionally
Best Sellers entries. Uploaded product images live under `/media/`.

### 2.2 Serve the frontend through a proxy (IMPORTANT)

Two browser cookies are involved in this API:

1. the **refresh-token cookie** (`SameSite=Strict`, path `/api/v1/accounts/`)
2. a **session cookie** used only for the sign-up handoff
   (`complete-registration`)

Both are `SameSite=Strict`. If your dev server runs on
`http://localhost:3000` and you call `http://127.0.0.1:8000` directly, that is
**cross-site** as far as the browser is concerned and the cookies will not be
sent — sign-up and token refresh will silently break.

The fix is to make everything same-origin in dev by proxying:

**Vite** (`vite.config.js`):

```js
export default {
  server: {
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/media": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
};
```

**Create React App** (`package.json`): add `"proxy": "http://127.0.0.1:8000"`.

With a proxy, your code just calls `/api/v1/...` with no host, and every cookie
flows normally. This also mirrors production, where both are same-domain.

> If you truly need cross-origin dev, the backend team must enable
> `CORS_ALLOW_CREDENTIALS` and `CSRF_TRUSTED_ORIGINS` — only plain
> (credential-less) cross-origin requests are allowed today
> (`CORS_ALLOWED_ORIGINS = ["http://localhost:3000"]`). The proxy is easier.

### 2.3 Testing sign-in without a phone

With the two dev flags set, `POST /accounts/request-otp/` responds with the
actual code:

```json
{ "detail": "OTP sent successfully.", "expires_in": 180, "debug_code": "482913" }
```

Use that code in `verify-otp`. Never enable `OTP_DEBUG_RETURN_CODE` in
production.

---

## 3. Authentication: the three flows

Everyone signs in with **phone number + OTP**. There are no passwords.

| Flow | Steps |
| --- | --- |
| **Sign in** (existing phone) | `request-otp` → `verify-otp` → response has `access`, cookie is set. Done. |
| **Sign up** (new phone) | `request-otp` → `verify-otp` → response says `national_id_required: true` (no user exists yet) → `complete-registration` with the national ID → user is created, `access` returned, cookie set |
| **Stay signed in** | On every 401: `POST /accounts/token/refresh/` with an empty body `{}` → new `access` in the body, new cookie set automatically. If the refresh returns 401, the session is over → show login. |
| **Sign out** | `POST /accounts/logout/` with the Bearer header → backend revokes the refresh token and clears the cookie. Then drop your in-memory token. |

Your responsibilities as the frontend:

1. Keep `access` in a **variable in memory** — never in `localStorage`.
2. Send `Authorization: Bearer <access>` on protected requests.
3. On 401 → refresh once → retry once → if still 401, go to the login screen.
4. On app boot (page reload), call refresh once to restore the session —
   the cookie survived the reload even though your variable did not.

The ready-made client below implements all of this.

---

## 4. Copy-paste API client

### 4.1 `api.js` — fetch wrapper with automatic refresh (vanilla JS)

```js
// api.js — minimal API client with automatic token refresh.
// No dependencies; works in any framework or none.
const API = "/api/v1";

let accessToken = null;    // in memory ONLY — never localStorage
let refreshPromise = null; // prevents parallel requests triggering parallel refreshes

export function setAccessToken(token) {
  accessToken = token;
}

export function isLoggedIn() {
  return accessToken !== null;
}

// Ask the backend for a new access token. The refresh token travels in the
// httpOnly cookie; the browser attaches it because of credentials: "include".
function refreshAccessToken() {
  if (!refreshPromise) {
    refreshPromise = fetch(`${API}/accounts/token/refresh/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",           // <-- always, for every API call
      body: JSON.stringify({}),         // empty body; token comes from the cookie
    })
      .then(async (res) => {
        if (!res.ok) {
          accessToken = null;           // 401: session really is over
          return false;
        }
        const data = await res.json();
        accessToken = data.access;      // cookie was rotated too — automatically
        return true;
      })
      .finally(() => {
        refreshPromise = null;          // allow the next refresh after this one
      });
  }
  return refreshPromise;
}

// Call once on app boot (e.g. in a top-level useEffect, before mounting
// protected routes). Returns true if a valid session was restored.
export async function restoreSession() {
  return refreshAccessToken();
}

async function toError(res) {
  let data = {};
  try {
    data = await res.json();
  } catch {
    /* empty body */
  }
  const err = new Error(data.detail || `Request failed (${res.status})`);
  err.status = res.status;
  err.fields = data; // field errors look like { "postal_code": ["..."] }
  return err;
}

export async function api(path, { method = "GET", body } = {}) {
  const res = await fetch(`${API}${path}`, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
    },
    credentials: "include",
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  // Access token expired -> refresh once, retry the original request once.
  if (res.status === 401 && (await refreshAccessToken())) {
    return api(path, { method, body }); // retry; a second 401 falls through
  }
  if (!res.ok) throw await toError(res);
  if (res.status === 204) return null;
  return res.json();
}
```

### 4.2 Sign-in flow

```js
// Step 1: send the OTP (the SMS arrives on the user's phone)
await api("/accounts/request-otp/", {
  method: "POST",
  body: { phone_number: "09123456789" },
});
// -> { "detail": "OTP sent successfully.", "expires_in": 180 }
//    (plus "debug_code" in development)

// Step 2: verify the code
const res = await api("/accounts/verify-otp/", {
  method: "POST",
  body: { phone_number: "09123456789", otp: "482913" },
});

if (res.national_id_required) {
  // New phone number: continue with sign-up (4.3)
  routeTo("/signup/national-id");
} else {
  // Existing user: logged in.
  // res = { "detail", "logged_in": true, "profile_complete": true, "access": "..." }
  setAccessToken(res.access);
  if (!res.profile_complete) routeTo("/profile/edit"); // names missing
  else routeTo("/");
}
```

Useful statuses from `verify-otp`: `400` wrong/expired/used code, `403`
account disabled, `429` too many wrong attempts.

### 4.3 Sign-up flow

```js
// After verify-otp answered { national_id_required: true }:
try {
  const res = await api("/accounts/complete-registration/", {
    method: "POST",
    body: { national_id: "0012345679" },
  });
  setAccessToken(res.access); // logged in; refresh cookie is set by the browser
  routeTo(res.profile_complete ? "/" : "/profile/edit");
} catch (err) {
  if (err.status === 400) showFieldErrors(err.fields); // invalid checksum
  if (err.status === 409) showError("This national ID is already registered.");
}
```

Notes:

- `complete-registration` must be called in the **same browser** that did
  `verify-otp` (it relies on a session cookie) — another reason the dev proxy
  from 2.2 matters.
- The national ID is validated with the Iranian checksum algorithm; a duplicate
  national ID or phone returns `409` and **no user is created**.
- National ID and phone number can never be changed by the user afterwards.

### 4.4 Logout

```js
export async function logout() {
  try {
    await api("/accounts/logout/", { method: "POST" }); // revokes + clears cookie
  } finally {
    setAccessToken(null); // even if the network call failed, go logged-out
    routeTo("/login");
  }
}
```

### 4.5 React notes

- Wrap `api` in a context provider; call `restoreSession()` **before** first
  render of guarded routes (e.g. `useEffect` + a `loading` state), then
  `GET /accounts/profile/` to hydrate the user object.
- If you use axios instead: the same logic is a response interceptor — on 401,
  call the refresh endpoint once (share a single in-flight promise like
  `refreshPromise` above), replay the original request, and on second failure
  clear the token and redirect to login. Set `withCredentials: true` on the
  axios instance.

---

## 5. Errors: what every status code means here

Error bodies are DRF-shaped: either `{"detail": "human readable message"}` or
field errors `{"postal_code": ["This field is required."]}`.

| Status | Meaning in this API | What to do |
| --- | --- | --- |
| `400` | Validation failed (bad input, inactive product, incomplete profile…) | Show `detail` or the field errors |
| `401` | Access token expired/invalid — **or** refresh failed (session over) | Handled automatically by `api()`; if you still see it, route to login |
| `403` | Action not allowed (disabled account, sign-up without prior OTP) | Show the message |
| `404` | Does not exist **or belongs to another user** (orders, addresses, payments) | Treat as "not found"; never probe for other users' data |
| `409` | Conflict: national ID / phone already registered during sign-up | Show "already registered" |
| `429` | OTP rate limit hit | Body: `{ "detail", "code", "retry_after" }` — `retry_after` is seconds; show a countdown |
| `502` | Payment gateway (Zibal) failure | "Payment gateway unavailable, try again" |
| `503` | SMS provider failure | "Could not send the code, try again later" |

`429` example:

```json
{ "detail": "Please wait before requesting another code.", "code": "cooldown", "retry_after": 63 }
```

---

## 6. Catalog (all public — no auth needed)

### `GET /api/v1/products/`

Paginated. Filters (combineable):

- `?category=<id>` — products in that category
- `?subcategory=<id>` — products in that subcategory
- `?search=<text>` — case-insensitive match on product **name or description**

Only active products are ever returned. One product looks like:

```json
{
  "id": 1,
  "name": "Leather Wallet",
  "description": "Handmade, brown.",
  "price": 250000,
  "image": "http://127.0.0.1:8000/media/products/wallet.jpg",
  "categories": [1],
  "category_names": ["Accessories"],
  "subcategories": [3],
  "subcategory_names": ["Wallets"],
  "is_active": true,
  "created_at": "2026-01-01T10:00:00+03:30"
}
```

- `price` is in **Toman**. Render it directly; add no zeros, no conversion.
- `image` is an **absolute URL** (or `null` if the product has no image — show
  a placeholder).
- `category_names` / `subcategory_names` are the display-ready names;
  the `categories` / `subcategories` id arrays are for linking.

### Other catalog endpoints

| Endpoint | Returns |
| --- | --- |
| `GET /api/v1/products/{id}/` | One product (same shape) |
| `GET /api/v1/categories/` | Categories, each with a nested `subcategories` array |
| `GET /api/v1/categories/{id}/` | One category |
| `GET /api/v1/categories/{id}/subcategories/` | Subcategories of one category (paginated) |
| `GET /api/v1/subcategories/?category=<id>` | Subcategories, optionally filtered |
| `GET /api/v1/best-sellers/` | Curated, ordered list of products — **plain array**, not paginated |

Category shape:

```json
{
  "id": 1,
  "name": "Accessories",
  "is_active": true,
  "subcategories": [
    { "id": 3, "name": "Wallets", "category": 1, "category_name": "Accessories", "is_active": true }
  ],
  "created_at": "2026-01-01T09:00:00+03:30"
}
```

---

## 7. Profile and addresses (Bearer required)

### `GET /api/v1/accounts/profile/`

```json
{
  "phone_number": "09123456789",
  "national_id": "0012345679",
  "first_name": "Sara",
  "last_name": "Ahmadi",
  "full_name": "Sara Ahmadi",
  "addresses": [
    { "id": 1, "address": "Tehran, ...", "postal_code": "1234567890",
      "created_at": "...", "updated_at": "..." }
  ]
}
```

- `phone_number` and `national_id` are **read-only** (managed by the sign-up
  flow). Send `PATCH {"first_name": "...", "last_name": "..."}` to update the
  rest. Everything else changes via the endpoints below.
- `profile_complete` (from sign-in) is `true` when `national_id`,
  `first_name` and `last_name` are all set — **orders are rejected until the
  profile is complete** (with a clear `400` message). Gate the checkout behind
  a profile check.

### Addresses: `GET|POST /api/v1/accounts/addresses/` and `GET|PATCH|DELETE /api/v1/accounts/addresses/{id}/`

```json
{ "address": "Tehran, Valiasr St., ...", "postal_code": "1234567890" }
```

- `postal_code` must be exactly 10 digits.
- Users only ever see and modify **their own** addresses (a foreign id is `404`).
- The newest address is used as the shipping address by default at checkout.

---

## 8. Checkout and payment, end to end

The backend keeps **no cart**. The cart lives entirely in your frontend
(state/context/localStorage is fine for it); `POST /orders/` turns the cart
into an order at checkout.

### The flow at a glance

```text
profile check -> create order -> initiate payment -> Zibal page
                                                      |  (customer pays)
                              backend verifies  <----- callback redirect
                                                      |
                              result page ?status=paid|failed&order_number=...
```

### Step by step

**1. Gate the checkout.** `GET /accounts/profile/`; require
`first_name`, `last_name` and at least one address. Then:

**2. Create the order.**

```js
const order = await api("/orders/", {
  method: "POST",
  body: {
    items: [
      { product_id: 1, quantity: 2 },
      { product_id: 4, quantity: 1 },
    ],
    address_id: 3, // optional; defaults to the user's newest address
  },
});
```

Response `201` (one order):

```json
{
  "id": 7,
  "order_number": "20260901-3F9A1C2D",
  "status": "pending",
  "total_price": 550000,
  "payment_status": null,
  "items": [
    { "id": 10, "product": 1, "product_name": "Leather Wallet",
      "unit_price": 250000, "quantity": 2, "total_price": 500000 }
  ],
  "shipping_address": "Tehran, Valiasr St., ...",
  "shipping_postal_code": "1234567890",
  "created_at": "..."
}
```

- `unit_price` is snapshotted at purchase time — it does **not** change if the
  product's price changes later.
- Send **each product at most once** with a merged quantity (`2 × product 1`
  as one line, not two lines of 1). Quantities are 1–99.
- Possible errors: `400` (incomplete profile / inactive or unknown product /
  empty cart / quantity out of range).

**2b. "Custom Design" checkbox (optional).** When the customer checks it on
the checkout page, the design section appears (description + 1-3 images +
an item picker over the submitted items). Then send `multipart/form-data`
instead of JSON:

```js
const form = new FormData();
form.append("items", JSON.stringify([
  { product_id: 1, quantity: 2 },
  { product_id: 4, quantity: 1 },
]));
form.append("address_id", "3");
form.append("custom_design_product_ids", JSON.stringify([1])); // subset of items
form.append("custom_design_description", "Print my logo on the front");
form.append("images", file1); // 1-3 files: JPEG/PNG/WEBP, <= 5 MB each
await fetch("/api/v1/orders/", { method: "POST", body: form, ...auth });
```

- Backend prices every selected item **+30%**; mirror that in your client-side
  totals and mark selected rows visually before submitting.
- The response's `items[].unit_price` already includes the surcharge, and the
  `custom_design` block carries `description`, `surcharge_percent`, `status`
  and `order_items` (the ids of the customized items).
- Validation is server-side and all-or-nothing: `custom_design_product_ids`
  must be a subset of `items`, and description + 1-3 images are required
  together with the ids (sending design fields without a selection is a `400`).

**3. Start the payment.**

```js
const payment = await api("/payments/initiate/", {
  method: "POST",
  body: { order_id: order.id },
});
// 201: { "detail", "track_id": "12345", "payment_url": "https://gateway.zibal.ir/start/12345", "amount": 550000 }
```

**4. Redirect the whole page** (not an iframe, not fetch) to the gateway:

```js
window.location.href = payment.payment_url;
```

**5. The customer pays on Zibal.** Zibal then redirects their browser to the
backend callback (`ZIBAL_CALLBACK_URL`). The backend verifies the payment
**server-side** (the callback's own success flag is never trusted), marks the
payment and the order paid in one transaction, and sends the confirmation SMS.

**6. Show the result.** The callback finally redirects the browser to your
result page — set `FRONTEND_PAYMENT_RESULT_URL` in the backend `.env`
(e.g. `http://localhost:5173/payment/result`). Your page receives:

```text
/payment/result?status=paid&order_number=20260901-3F9A1C2D&detail=Payment+successful
```

`status` is `paid` or `failed`; `order_number` is present when known. Build
this page to parse the query string and show success/failure.

**7. (Recommended) confirm before celebrating.** The redirect alone is not
proof of payment — anyone can type the URL. On the result page, call:

```js
const res = await api("/payments/verify/", {
  method: "POST",
  body: { track_id: trackId },
});
// 200: { "detail", "order_number", "order_status", "payment_status" }
```

Keep `track_id` from step 3 (e.g. in `sessionStorage`) to make this call.
Verify is **idempotent** — safe to call more than once. On success, fetch
`GET /orders/{id}/` to show the final order state.

### Order & payment statuses

| `order.status` | Meaning |
| --- | --- |
| `pending` | Created, not yet paid (the only state that can be paid) |
| `paid` | Payment verified |
| `processing` | Being prepared (staff sets this) |
| `shipped` / `delivered` | Fulfilment states |
| `cancelled` | Cancelled — set by staff in Django Admin only; there is no automatic cancellation (a failed payment leaves the order `pending`, so it can be paid again) |

`payment_status` on an order: `null` (never attempted), `pending`, `success`,
`failed`. If a user retries payment, `POST /payments/initiate/` again on the
same pending order.

---

## 9. Endpoint cheat sheet

All relative to `/api/v1/`. `PB` = Bearer required, `pub` = public.

| Method & path | Auth | Purpose |
| --- | --- | --- |
| `POST /accounts/request-otp/` | pub | Send OTP SMS. Body: `{phone_number}` |
| `POST /accounts/verify-otp/` | pub | Verify code → `access` + cookie, or `national_id_required: true` |
| `POST /accounts/complete-registration/` | pub (session) | Finish sign-up with `{national_id}` |
| `POST /accounts/token/refresh/` | cookie | Empty body `{}` → new `access` + rotated cookie |
| `POST /accounts/logout/` | PB | Revoke refresh token, clear cookie |
| `GET /accounts/profile/` | PB | Get profile (with addresses) |
| `PATCH /accounts/profile/` | PB | Update `first_name` / `last_name` |
| `GET /accounts/addresses/` | PB | List addresses |
| `POST /accounts/addresses/` | PB | `{address, postal_code}` |
| `GET / PATCH / DELETE /accounts/addresses/{id}/` | PB | One address (own only) |
| `GET /products/` | pub | Catalog. `?category=` `?subcategory=` `?search=` `?page=` |
| `GET /products/{id}/` | pub | One product |
| `GET /categories/` · `/categories/{id}/` | pub | Categories (with nested subcategories) |
| `GET /categories/{id}/subcategories/` | pub | Subcategories of a category |
| `GET /subcategories/?category=` | pub | Subcategories |
| `GET /best-sellers/` | pub | Curated list (**plain array**) |
| `GET /orders/` | PB | My orders (paginated) |
| `POST /orders/` | PB | Create order from cart: `{items:[{product_id, quantity}], address_id?}` — or **multipart** with `custom_design_product_ids` + `custom_design_description` + 1-3 `images` for the Custom-Design checkbox (+30% on selected items) |
| `GET /orders/{id}/` | PB | One of my orders |
| `POST /payments/initiate/` | PB | `{order_id}` → `{track_id, payment_url, amount}` |
| `POST /payments/verify/` | PB | `{track_id}` → confirm payment (idempotent) |
| `GET /payments/callback/` | — | Called by Zibal's redirect, **not by your code** |

---

## 10. Pitfalls checklist

Print this. Every line here has bitten someone.

- [ ] **Never** store the access token in `localStorage` (XSS-stealable) — memory only.
- [ ] **Never** try to read the refresh cookie in JS — it is `httpOnly` by design.
- [ ] Pass `credentials: "include"` on **every** API call (and `withCredentials` for axios).
- [ ] In dev, use the proxy from section 2.2 — calling `127.0.0.1:8000` directly from `localhost:3000` silently breaks the cookies (`SameSite=Strict`).
- [ ] On app boot, call refresh **once** to restore the session before guarding routes.
- [ ] On 401: refresh once, retry once, then log out. Never loop refreshes.
- [ ] After `verify-otp`, branch on `national_id_required` before assuming login succeeded.
- [ ] `complete-registration` only works in the same browser/session that did `verify-otp`.
- [ ] Checkout requires a **complete profile** (`first_name`, `last_name`) — gate it, or handle the `400`.
- [ ] Send each product **once** per order with a merged quantity.
- [ ] `?category=` / `?subcategory=` take **numeric ids**, not names.
- [ ] `GET /best-sellers/` returns a **plain array**; everything else is a `{count, next, previous, results}` envelope — normalize in one place.
- [ ] All money values are **Toman** integers. No conversion, no decimals.
- [ ] Product `image` is an absolute URL or `null` — always render a fallback.
- [ ] `404` on an order/address/payment can mean "not yours" — do not use it to probe other users' data.
- [ ] Handle `429` on OTP endpoints with the `retry_after` countdown instead of hammering the button.
- [ ] Redirect to Zibal with `window.location.href` — the gateway is a full-page redirect, never a fetch.
- [ ] `POST /orders/` Custom Design is **multipart/form-data**, not JSON: `items` and `custom_design_product_ids` are JSON **strings**, `images` are 1-3 file parts (JPEG/PNG/WEBP, <= 5 MB each) and must be sent **together** with a description. Selected items cost **+30%** — show that in the totals before the customer submits.
- [ ] Treat the payment result redirect as untrusted; confirm via `POST /payments/verify/` before showing "payment successful".
- [ ] The sign-up cookie flow means the API is **browser-first**. For Postman/mobile clients, `token/refresh` also accepts `{"refresh": "<token>"}` in the body — but the SPA should always use the cookie.





