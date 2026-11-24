# Backend Architecture

This explanation describes the implemented Django backend. It supports Django
`>=5.1`, Python `>=3.12`, PostgreSQL, and Django REST Framework.

## Components and boundaries

| App | Responsibility |
| --- | --- |
| `accounts` | User, OTP, profile, and address workflows |
| `products` | Catalog search, filters, product attributes, and best sellers |
| `orders` | Checkout, snapshots, custom designs, and image validation |
| `payments` | Zibal client and payment orchestration |
| `notifications` | Kavenegar verify/lookup client |
| `config` | Settings and root routes |

Views adapt HTTP requests. Serializers validate input, services own business
rules and transactions, and provider modules isolate external HTTP calls.
Follow `serializer -> service -> model/provider -> response` when adding work.

Product search is implemented in `ProductViewSet.get_queryset`. It starts from
the active-product queryset and adds one `Q` filter for `name` or `description`
when `search.strip()` is non-empty. DRF evaluates the catalog queryset once
when building the response, with the bounded related-object prefetches already
defined by the view; it does not perform work per input character. Clients
should submit on Enter or an explicit search-button action.

## Domain behavior

Users authenticate by normalized phone number and OTP. Codes are random, stored
as salted hashes, expired, and protected by cooldown, hourly, and attempt limits.
Existing users receive an access token and refresh cookie. New users complete
registration with a unique valid national ID and a mandatory acceptance of the
Website Rules and Regulations (`terms_accepted`). Each acceptance is written to
`TermsAcceptance` in the same transaction that creates the user, snapshotting
the rules version (`TERMS["CURRENT_VERSION"]`), the national ID, the timestamp,
the client IP, and the user agent. The table is append-only: rows are read-only
in Django Admin, protected from deletion, and unique per user and rules version,
so a later rules change adds a new version instead of rewriting the old
evidence. The profile API reports the latest acceptance; acceptance rows are
never written or edited through the API. Profile completion requires the
national ID, both names, and at least one address.

Orders snapshot product prices and shipping addresses at creation; the total
at that point is the item subtotal. Delivery is selected when payment is
initiated, and its method and fee are snapshotted then. Checkout locks product
rows and validates prices server-side. It does not merge duplicate lines or
decrement stock. New order numbers use `YYYY-MM-DD-XXXXXXXX`, with an
eight-character uppercase hexadecimal suffix. The order list API returns
compact order summaries, while the order detail API returns the complete
customer-facing item, option, and delivery data; staff detail responses also
include customer identity and payment summaries.

Order deletion is not exposed through the public API. In Django Admin,
superusers can delete orders and their item-option snapshots; protected
relations, including payments, can still prevent deletion. Ordinary staff
cannot delete item-option snapshots.

Custom designs are one-to-one with orders, link selected items, and store
re-encoded Pillow images under `designs/YYYY/MM/`.
The custom-design *intake* is feature-flagged: with
`CUSTOM_DESIGN_ENABLED=False` (the default) the checkout endpoint ignores the
design fields, while the models, admin, pricing logic, and historical designs
stay fully functional — set the variable to `True` to restore the flow.

Product attributes (options) are defined once in their own **Product
attributes** Django Admin section: `ProductAttribute` (globally unique stable
key, display name, `select`/`text` input type, required/active flags) with
`AttributeChoice` rows carrying admin-set `price_delta` amounts. Each
subcategory then selects the attributes it uses, so one attribute (for
example `car_type`) can be shared by several subcategories without
redefining its key or choices. Checkout validates submitted selections
against the active attributes selected on the reference subcategory, adds
choice deltas to the backend-computed price
(`unit_price = base + sum(deltas)`), and stores immutable per-item snapshots
(`OrderItemOption` keys, labels, text values, and applied deltas) that keep
historical orders correct after later definition edits, detachment, or
deactivation. To configure them, create the attribute under **Product
attributes** (save it, then add each choice's key, display label, and price
delta) and open **Subcategories** to select the attributes that apply.
Choices apply only to `select` attributes; `text` attributes accept
customer-entered values and have no configured choices. The storefront sees
the active attributes of a subcategory through a single top-level `options`
array on the product list filtered by `?subcategory=<id>` and on
`GET /subcategories/{id}/` (same shape as the product detail), plus the same
`options` on `GET /products/{id}/`; because options are a property of the
subcategory shared by all its products, each listing returns them once
instead of inside every product, a customer browsing a subcategory can show
product detail pages from that listing alone, and the product detail endpoint
remains the fallback for products reached outside a subcategory context
(search, best-sellers, deep links). The admin prices a product against its
default choice (`price_delta: "0"`), so the stored price is what the
storefront displays before an option is selected; the API exposes no
preselected option.

## Payment and notification flow

Initiation locks the order, requires an active delivery method, snapshots its
current fee, adds it once to the item subtotal, and rejects a second pending
attempt. Pending-payment orders cannot have their items edited. The gateway
request always sends the customer's phone number and national ID as Zibal's
`mobile` and `nationalCode` fields for card loading and ownership validation.

Verification checks the gateway amount in Rial against the stored Toman amount
multiplied by 10. Row locks make completion idempotent; successful payment and
order status are committed together before notifications are attempted. If
another attempt has paid the order or the order is otherwise closed, an
additional successful charge is marked `needs_reconciliation` rather than
recorded as a second success. An amount mismatch also marks the failed payment
for reconciliation. Flagged
attempts remain visible in Django Admin and staff payment summaries; the
Payments admin list can filter by this flag. Reconciliation and refunds are
manual, and no automatic refund is issued.

Customer payment SMS uses Kavenegar's `verify/lookup.json` endpoint, which can
only send templates approved in the Kavenegar panel; tokens (order number,
amount) are sanitized to latin letters and digits before sending. The
administrator helper is selected by the
presence of `order.custom_design`: custom orders use
`send_custom_order_paid_sms_to_admin`, and normal orders use
`send_order_paid_sms_to_admin`. Notification failures are logged and do not
change payment state. Both admin helpers send through Kavenegar to
`ADMIN_PHONE_NUMBER`; when it is unset they log a warning and skip.

## Testing and known gaps

Run `uv run python manage.py test`. Tests use Django `TestCase` and patch Zibal
and Kavenegar boundaries. The API is documented through an OpenAPI 3 schema
generated by drf-spectacular (`/api/schema/`); the interactive Swagger UI is
served at `/api/docs/` (and Redoc at `/api/redoc/`) when `DJANGO_DEBUG=True`.
Current gaps include synchronous SMS, no stock decrement, and best-effort
per-process OTP throttling through the configured Django cache. Local CORS and
CSRF origins default to `http://localhost:3000` and
`http://127.0.0.1:3000` and are overridable through
`DJANGO_CORS_ALLOWED_ORIGINS` / `DJANGO_CORS_TRUSTED_ORIGINS`; production
HTTPS and HSTS policy belongs at the deployment boundary.