# Docker Deployment (Django + AI + Stripe Webhook Route)

This setup runs:
- `web`: Django app (marketplace + payments)
- `ai-quality`: YOLO quality API
- `ai-recommend`: recommendation API
- `nginx`: single gateway with separate API routes

## 1) Prepare `.env`
Copy and update:

```bash
cp .env.example .env
```

Set Stripe keys in `.env`:
- `STRIPE_SECRET_KEY`
- `STRIPE_PUBLISHABLE_KEY`
- `STRIPE_WEBHOOK_SECRET` (from `stripe listen`)

## 2) Build and start

```bash
docker compose up --build
```

App entrypoint:
- `http://localhost:8080/`

## 3) API routes (separated)

- Django app: `http://localhost:8080/`
- Quality AI route: `http://localhost:8080/api/quality/`
  - Predict endpoint: `POST http://localhost:8080/api/quality/predict`
- Recommendation AI route: `http://localhost:8080/api/recommend/`
  - Recommend endpoint: `POST http://localhost:8080/api/recommend/recommend`
- Stripe webhook route: `http://localhost:8080/api/stripe/webhook/`

## 4) Stripe webhook forwarding

Run Stripe CLI using the dedicated API route:

```bash
stripe listen --forward-to http://127.0.0.1:8080/api/stripe/webhook/
```

Copy the printed `whsec_...` into `.env` as `STRIPE_WEBHOOK_SECRET`, then restart:

```bash
docker compose restart web
```

## 5) Notes

- SQLite DB is persisted via `sqlite_data` volume at `/app/data/db.sqlite3`.
- Media and weights are persisted in named volumes.
- Django internally calls AI services directly over Docker network:
  - `http://ai-quality:8000/predict`
  - `http://ai-recommend:8000/recommend`
