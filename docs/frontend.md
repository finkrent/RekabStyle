# Frontend Integration Guide

This how-to guide covers browser integration. There is no official frontend in
the repository.

## Local proxy

Use a dev proxy so the SPA calls the API on its own origin:

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

Refresh and sign-up cookies are `SameSite=Strict`. Credentials are enabled for
localhost ports 3000, but same-origin proxying is still recommended.

## Authentication

1. Request an OTP at `/accounts/request-otp/`.
2. Verify it at `/accounts/verify-otp/`.
3. Store the returned access token in memory only.
4. For a new phone, complete registration in the same browser session. The
   response includes a new `access` token and sets the refresh cookie, so no
   separate sign-in step is needed.
5. Send `Authorization: Bearer <access>` on protected requests.

Include `credentials: "include"`. On startup refresh once. On a `401`, refresh
once and retry once; a second `401` ends the session. The refresh token is
httpOnly and cannot be read by JavaScript.

Money fields are Decimal strings in Toman. Parse them for arithmetic or display;
never convert them to Rial.

## Requests

### Catalog

`GET /products/` returns 8 products per page. Follow the returned `next` URL
(it keeps the `?subcategory=`/`?q=` filters) and treat `next: null` as the
last page; `?page_size=` is not supported. `GET /products/{id}/` returns an
`options` array — the active attributes of the product's reference
subcategory. `select` options carry `choices` (each with a `price_delta`
added to the product price); `text` options carry `"price_delta": "0"` and
your own `value`. Products assigned to several subcategories need an
explicit `?subcategory=<id>` on the detail call.

Product lists, subcategory details, and best-seller lists include unavailable
products. When `is_active` is `false`, render the product card as unavailable
(for example, gray it out) and disable its purchase controls. The backend
rejects checkout for inactive products even if a client submits one.

### Checkout (normal, JSON)

```js
const order = await api("/orders/", {
  method: "POST",
  body: JSON.stringify({
    items: [
      {
        product_id: 15,
        quantity: 2,
        subcategory_id: 2,
        selected_options: [
          { option_id: 10, choice_id: 2 },
          { option_id: 11, value: "پژو ۲۰۷" },
        ],
      },
    ],
    address_id: 3,
  }),
});
```

`option_id`/`choice_id` are the numeric ids from the product detail
`options`. `subcategory_id` and `selected_options` are optional; required
attributes (per the product detail response) must all be submitted.

### Cart updates

To change a pending order without creating a new one, send
`PATCH /orders/{id}/` with the full `items` list (same shape as checkout):
include an item to add it or change its quantity, omit it to remove it. The
response is the updated order; only pending orders without a custom design
can be edited.

### Custom design (multipart)

Custom design requires `FormData`. Do not set `Content-Type` manually:

```js
const form = new FormData();
form.append("items", JSON.stringify([{ product_id: 1, quantity: 2 }]));
form.append("address_id", "3");
form.append("custom_design_product_ids", JSON.stringify([1]));
form.append("custom_design_description", "Print my logo on the front");
form.append("images", file);
await api("/orders/", { method: "POST", body: form });
```

Send one to three JPEG, PNG, or WEBP files, each at most 5 MiB. Selected items
receive the configured surcharge, 30 percent by default. The server is the
source of truth for prices and validation.

## Payments

1. Initiate with `POST /payments/initiate/` and `{ "order_id": order.id }`.
2. Preserve `track_id` and redirect the full page to `payment_url`.
3. Let Zibal redirect to the backend callback.
4. Preserve the original track ID; the callback does not replace it.
5. Confirm with `POST /payments/verify/` before displaying success.

The callback query is not proof of payment. Verification is server-side,
amount-checked, and idempotent. A verified unsuccessful payment changes the
order status to `failed`; the failed order remains visible until scheduled
cleanup removes it after 30 days.

## Errors

`400` means validation or payment failure, `401` means missing/expired access,
`403` means forbidden account or sign-up state, `404` means missing or foreign
resource, `409` means duplicate registration data, `429` means OTP limiting,
`502` means Zibal failure, and `503` means OTP SMS failure.