# Local food marketplace — payment & refunds subsystem <br><br>

**Document type:** Technical guide (payment scope only) <br>
**Repository area:** `payments/` app, Stripe integration, and related customer / admin surfaces <br>
**Audience:** Teammates and markers running the project on **Windows, Linux, or macOS** without prior local setup <br>
**Important:** This guide uses **placeholder values only** for secrets (`pk_test_xxx`, `sk_test_xxx`, `whsec_xxx`). Store real values in a **local** `.env` file. Do **not** commit `.env` or paste its contents into reports or chats. <br><br>

---

## 1. Introduction

This subsystem implements a **university-style marketplace checkout** that is close to real-world practice but deliberately bounded in scope. Customers pay with **Stripe Checkout** (hosted page). The server records a **`Payment`**, listens for a **signed webhook**, and runs **idempotent fulfillment** (stock, cart, order status). **Refunds** go through a **customer request → operator review → admin execution** path with Stripe **`Refund.create`** and idempotency keys.

The default database in settings is **SQLite** (`db.sqlite3` beside `manage.py`). Webhook handling is designed to remain usable under SQLite for coursework; heavy parallel webhook load is not a design target.

<br><br>

## 2. Acknowledgements and positioning

Payment flows follow **Stripe’s test-mode documentation** and **Django** admin patterns. Card data is collected on **Stripe-hosted** pages, not in this application’s forms beyond normal checkout redirects. This README is **standalone**: follow sections in order to run payments locally.

<br><br>

## 3. Repository layout (payment-relevant)

The Django project root used in commands is the folder that contains **`manage.py`** (referred to here as **`main/`**).

```
main/
├── manage.py
├── README_PAYMENTS.md          # this document
├── requirements.txt
├── .env                        # you create this locally (not committed)
├── db.sqlite3                  # created after migrate (default SQLite)
├── brfn/
│   ├── settings.py             # loads .env; Stripe-related settings
│   ├── urls.py                 # includes payments.urls under /payments/
│   └── admin_actions.py        # shared admin “Select Action” label helper
├── payments/
│   ├── models.py               # Payment, RefundRequest, PaymentEvent, StripeWebhookReceipt
│   ├── stripe_service.py       # Checkout Session, webhook verify, Refund.create
│   ├── checkout.py             # payment_pending order + start Checkout (test-key guard)
│   ├── fulfillment.py         # webhook-driven fulfillment (idempotent)
│   ├── webhook_reliability.py # event_id dedupe (SQLite-friendly)
│   ├── views.py                # webhook, checkout return, refund pages, inbox
│   ├── refund_service.py       # single entry for processing approved refunds
│   ├── display.py              # customer-safe wording + USD formatting helpers
│   ├── admin.py                # Payment / RefundRequest / events / webhook receipts + analytics hook
│   └── templatetags/
│       └── payments_tags.py    # |usd and customer status filters
└── templates/
    ├── refund_request.html      # customer refund help
    ├── refund_inbox.html        # operator refund queue
    └── admin/payments/
        └── analytics.html       # optional admin KPI view (payment app)
```

Order detail templates and order views that **surface** payment summaries live outside `payments/` but consume **`payments.display`** and **`payments_tags`**; they are not re-documented file-by-file here.

<br><br>

## 4. Architecture summary

| Component | Responsibility |
|-----------|----------------|
| **Stripe Checkout** | Hosted payment UI; server creates **Session** + local **`Payment` (`pending`)**. |
| **`POST /payments/webhook/`** | Verifies **`Stripe-Signature`**; records **`StripeWebhookReceipt`** by unique **`event_id`**; runs **`handle_stripe_event`**. |
| **Fulfillment** | On **`checkout.session.completed`**: atomic **`Payment`** `pending` → `processing` claim, validations, stock decrement, cart clear, **`Payment`** `succeeded`, order leaves **`payment_pending`** for **`pending`** (awaiting producer workflow). |
| **Refunds** | **`RefundRequest`** lifecycle + **`refund_service.process_refund_request`** (idempotent Stripe refund). |
| **`payments/display.py`** | Customer-facing labels; internal audit strings stay off shopper pages. |

**HTTP routes (all prefixed `/payments/`):**

| Path | Purpose |
|------|---------|
| `POST …/webhook/` | Stripe webhooks |
| `…/checkout/success/`, `…/checkout/cancel/` | Browser return after Checkout |
| `…/refunds/request/<order_id>/` | Customer refund help |
| `…/refunds/inbox/` | Operator inbox |
| `…/refunds/<id>/(approve|reject|process|delete)/` | Inbox POST actions |

**Django admin extension:** when Django loads **`payments.admin`**, the app prepends an **analytics** route to the admin site (typically **`/admin/analytics/`**). It is a **demo dashboard**, not a financial system of record.

<br><br>

## 5. Roles and access control

### Customer

1. Cart → **Checkout** POST → creates an **`Order`** in **`payment_pending`** and a **`Payment`** row, then redirects to **Stripe Checkout**. <br><br>
2. After paying, Stripe redirects to **`/payments/checkout/success/`**. **Authoritative settlement** happens when **`checkout.session.completed`** is handled via the **webhook** (the browser return alone is not the source of truth). <br><br>
3. **Order detail** may show payment status, **payment history** rows, optional **receipt-style commission breakdown**, and **refund help** when eligible. <br><br>
4. **Refund help** page: customer submits a **reason** → **`RefundRequest`** starts as **`pending`**; later statuses reflect operator actions and settlement outcomes.

### Producer (`User.role == "producer"`)

- Does **not** capture cards. <br><br>
- May open **`/payments/refunds/inbox/`** together with staff and admin operators (see below). <br><br>
- **Approve / reject** from the inbox: if the user is a **producer without `is_staff`**, the server only allows these actions when the order is **single-producer** (multi-vendor orders require **staff**-level review for that path). <br><br>
- **Cannot** run **“Process refund”** in the inbox unless they are also **`is_staff`** or have **`role == "admin"`** (same rule as `refund_process_view`).

### Staff / admin operators

- **`is_staff`** **or** **`User.role == "admin"`** may **process refunds** (Stripe money movement) from the inbox or Django admin. <br><br>
- **`is_staff`** **or** **`role` in `admin` / `producer`** may access the **inbox** UI; effective approve/reject permissions still follow the producer rule above for non-staff producers. <br><br>
- **Django admin** exposes **`Payment`**, **`PaymentEvent`**, **`StripeWebhookReceipt`**, **`RefundRequest`**, and bulk actions (approve, reject, execute refund, superuser-only cleanup).

<br><br>

## 6. Environment variables (`.env`)

### 6.1 Create the file

From **`main/`** (next to `manage.py`):

1. Create **`.env`** (leading dot, UTF-8 text, one `KEY=value` per line). <br><br>
2. **Never commit** `.env`. <br><br>
3. `brfn/settings.py` loads it with **`python-dotenv`** (`load_dotenv(BASE_DIR / ".env")`).

### 6.2 Required placeholders (replace `xxx` with your test values)

```env
# Stripe — test mode only for this coursework path
STRIPE_PUBLISHABLE_KEY=pk_test_xxx
STRIPE_SECRET_KEY=sk_test_xxx
STRIPE_WEBHOOK_SECRET=whsec_xxx
```

| Variable | Role |
|----------|------|
| **`STRIPE_PUBLISHABLE_KEY`** | Publishable test key (`pk_test_…`) when the storefront needs Stripe configuration. |
| **`STRIPE_SECRET_KEY`** | Secret test key (`sk_test_…`) for Checkout Session creation, webhooks, and refunds. |
| **`STRIPE_WEBHOOK_SECRET`** | Signing secret (`whsec_…`) from **`stripe listen`** or the Dashboard endpoint that points at **`/payments/webhook/`**. |

### 6.3 Optional variables (examples only)

```env
STRIPE_API_VERSION=2024-11-20.acacia
STRIPE_CHECKOUT_CURRENCY=usd
STRIPE_WEBHOOK_MAX_BODY_BYTES=1048576
STRIPE_CHECKOUT_DEMO_CARD_ONLY=true
# STRIPE_CHECKOUT_PAYMENT_METHOD_TYPES=card
```

**Demo storefront guard:** `payments/checkout.py` refuses **non-test** secret keys for the hosted checkout path and expects a test publishable key **when** `STRIPE_PUBLISHABLE_KEY` is set. This is intentional for lab safety, not a guarantee of full production hardening.

<br><br>

## 7. Installation and database

### Python

Use **Python 3** as required by your module (3.11+ is a reasonable default). Check:

```bash
python --version
```

On many Linux or macOS systems, use **`python3`** instead of **`python`** if that is what your environment provides.

### Virtual environment (recommended)

```bash
python -m venv .venv
```

Activate:

- **Windows Command Prompt:** `.venv\Scripts\activate.bat` <br><br>
- **Windows PowerShell:** `.venv\Scripts\Activate.ps1` (if execution policy blocks scripts, adjust policy for your user or use **cmd** and `activate.bat` instead). <br><br>
- **Linux / macOS:** `source .venv/bin/activate`

### Dependencies

```bash
python -m pip install -r requirements.txt
```

`requirements.txt` pins a **minimum Django** and includes **`stripe`**, **`python-dotenv`**, and other project-wide packages; installing the full file is expected for this repo.

### Database

Default engine is **SQLite**. Apply migrations from **`main/`**:

```bash
python manage.py migrate
```

Create a superuser if you need Django admin (`createsuperuser`).

<br><br>

## 8. Running the application and tests

```bash
python manage.py runserver
```

Default URL: **`http://127.0.0.1:8000/`**. Complete checkout with **Stripe test cards** documented by Stripe (public examples such as **`4242 4242 4242 4242`** with a future expiry and any CVC in **test mode**).

**Automated payment tests:**

```bash
python manage.py test payments.tests
```

**Full project tests** (other apps included):

```bash
python manage.py test
```

<br><br>

## 9. Stripe CLI and webhooks

Local webhooks must be tunneled to your machine. Use the **Stripe CLI**.

### Install (cross-platform)

- Official docs: [Stripe CLI](https://stripe.com/docs/stripe-cli). <br><br>
- **Windows (Scoop, optional):**  
  `scoop bucket add stripe https://github.com/stripe/scoop-stripe-cli.git`  
  `scoop install stripe`

Verify:

```bash
stripe --version
```

### Login (once per developer machine)

```bash
stripe login
```

### Forward events to Django

With the dev server on the default port:

```bash
stripe listen --forward-to http://127.0.0.1:8000/payments/webhook/
```

The CLI prints a **`whsec_…`** signing secret. Put that value into **`.env`** as **`STRIPE_WEBHOOK_SECRET`**. If the CLI rotates the secret between runs, update `.env` to match.

### About `stripe trigger`

Commands such as:

```bash
stripe trigger checkout.session.completed
```

generate **synthetic** events. They are useful to confirm wiring and signature verification, but they **do not automatically** tie to a **`Payment`** row your storefront just created. For an **end-to-end** lab demo, completing Checkout **in the browser** after `stripe listen` is running is usually the most reliable path.

<br><br>

## 10. Payment flow (step-by-step)

1. Customer posts checkout → server persists **`Order`** (`payment_pending`) + **`OrderItem`** rows and a **`Payment`** (`pending`) with a Checkout **session id**, then returns the **Stripe Checkout URL**. <br><br>
2. Customer pays at Stripe → Stripe sends **`checkout.session.completed`** to **`/payments/webhook/`**. <br><br>
3. Server verifies the signature, ensures a **`StripeWebhookReceipt`** row for **`event_id`** (unique; retries and concurrent first deliveries are deduped safely for SQLite). <br><br>
4. **`fulfillment`** runs in a database transaction: claims **`pending` → `processing`** on the **`Payment`**, validates metadata and amounts, decrements stock, clears the customer’s cart, sets **`Payment`** to **`succeeded`**, and sets the **order** status from **`payment_pending`** to **`pending`** (producer-facing workflow in the orders app). <br><br>
5. Duplicate deliveries: **receipt idempotency** plus the **payment status claim** prevent double fulfillment under normal retry patterns.

<br><br>

## 11. Refund flow (step-by-step)

1. Customer uses **refund help** → creates **`RefundRequest`** (**`pending`**). <br><br>
2. Operators **approve** or **reject** via inbox or Django admin (see **Section 5** for producer constraints). <br><br>
3. A user with **`is_staff`** or **`role == "admin"`** runs **Process refund** → **`refund_service.process_refund_request`**: stable **Stripe idempotency key** per request, status transitions **`approved` / failed retry → `processing` → `completed` or `failed`**, with **`Payment`** statuses updated accordingly. <br><br>
4. Customer-visible text comes from **`payments/display.py`** and templates, **not** raw **`PaymentEvent.event_type`** strings.

<br><br>

## 12. Admin operations (Django admin + inbox)

| Action | Where | Notes |
|--------|-------|------|
| Inspect payments / events / webhook receipts | Django admin | Operator-oriented fields (e.g. masked references) are expected here. |
| Bulk refund actions | **`RefundRequest`** admin | Approve, reject, execute, superuser cleanup — labels use the shared **“Select Action”** placeholder pattern project-wide. |
| Row-level inbox | **`/payments/refunds/inbox/`** | Matches the same business rules as above for approve / reject / process. |
| KPI-style analytics | **`/admin/analytics/`** (after `payments.admin` is imported) | **Illustrative** totals; not a substitute for accounting systems. |

<br><br>

## 13. Customer-facing payment display

- **Payment history** on the order view uses **`build_customer_payment_history_rows`**: friendly status text, **two-decimal** USD via **`|usd`**, and **no** Stripe session or intent identifiers in the HTML. <br><br>
- **Receipt-style breakdown** (items total, marketplace fee, producer share) appears only when commission data exists and the payment is in a **post-payment** state; amounts are quantized for **two decimal places** in display helpers. <br><br>
- **Refund statuses** use the customer label map in **`payments/display.py`** (not internal enum strings on shopper pages).

<br><br>

## 14. Troubleshooting and practical limits

| Symptom | What to verify |
|---------|----------------|
| Checkout will not start | `.env` readable? **`STRIPE_SECRET_KEY`** starts with **`sk_test_`**? Check server logs. |
| Webhook **400** / invalid signature | **`STRIPE_WEBHOOK_SECRET`** matches the **`stripe listen`** secret for the **same** forward URL. |
| Payment stays **`pending`** / order never promotes | Is **`stripe listen`** running? Did fulfillment raise? Inspect **`PaymentEvent`** rows in admin (internal audit). |
| **`database is locked`** on SQLite | Avoid many parallel webhook writers against one SQLite file; prefer a **single** `stripe listen` and modest concurrency. |
| Refund process denied | Confirm the user is **`is_staff`** or **`role == "admin"`** for **process**; producers alone cannot move money without those flags. |

This subsystem **does not** promise production-scale concurrency on SQLite or full financial compliance.

<br><br>

## 15. Security, intentional boundaries, and optional checklist

### Security

- Never commit **`sk_live_`**, live webhook secrets, or `.env`. <br><br>
- Webhook bodies are **signature-verified** before business logic runs. <br><br>
- Use **test keys** for all coursework unless you have an approved production process.

### Intentionally not included

- Production deployment hardening (TLS termination at the edge, secrets manager, horizontal scaling). <br><br>
- **Automated producer payouts** (no Connect payout pipeline in this codebase). <br><br>
- Alternative payment service providers. <br><br>
- Full chargeback / dispute automation.

### Optional hand-in checklist

- [ ] `.env` present with **`pk_test_xxx` / `sk_test_xxx` / `whsec_xxx`** placeholders replaced by **your** test values only on local disk. <br><br>
- [ ] `python manage.py check` and **`python manage.py test payments.tests`** succeed. <br><br>
- [ ] Browser checkout completes and, with **`stripe listen`**, the order reaches the **paid / awaiting producer** path. <br><br>
- [ ] Customer refund page shows **plain-language** statuses (no raw Stripe vocabulary). <br><br>
- [ ] Admin or staff **`role == "admin"`** can **process** a test refund after approval. <br><br>
- [ ] Replayed webhook for the same **`event_id`** does **not** double-apply fulfillment.

<br><br>

<h2 align="center">— End of payment subsystem README —</h2>
