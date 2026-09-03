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
4. For a new phone, complete registration in the same browser session.
5. Send `Authorization: Bearer <access>` on protected requests.

Include `credentials: "include"`. On startup refresh once. On a `401`, refresh
once and retry once; a second `401` ends the session. The refresh token is
httpOnly and cannot be read by JavaScript.

Money fields are Decimal strings in Toman. Parse them for arithmetic or display;
never convert them to Rial.

## Requests

Normal checkout is JSON:

```js
const order = await api("/orders/", {
  method: "POST",
  body: JSON.stringify({
    items: [{ product_id: 1, quantity: 2 }],
    address_id: 3,
  }),
});
```

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
amount-checked, and idempotent. A failed payment leaves the order pending.

## Errors

`400` means validation or payment failure, `401` means missing/expired access,
`403` means forbidden account or sign-up state, `404` means missing or foreign
resource, `409` means duplicate registration data, `429` means OTP limiting,
`502` means Zibal failure, and `503` means OTP SMS failure.