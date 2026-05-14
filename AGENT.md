# AGENT.md

## Project Snapshot

This is a Django-based local food marketplace platform with multi-role flows:
- `customer`
- `producer`
- `admin`

Core apps in this repository:
- `users` (auth/profile/roles)
- `products` (catalog, producer tools, content, quality inspection UI)
- `orders` (cart/checkout/orders/recurring orders)
- `payments`
- `sustainability`

Frontend is server-rendered Django templates (Tailwind CDN + custom styling), with primary layout in:
- `templates/base.html`

## Current Navigation State

Navigation is centralized in `templates/base.html`:
- Desktop has core links plus click-based dropdown menus (`Tools`, `Producer`).
- Mobile menu is sectioned (`Main`, `Tools`, `Producer`).
- Dropdowns are click-triggered via JS (`data-dropdown-toggle`) and close on outside click.

## Quality Inspection (Current Behavior)

Current quality inspection is **API-driven inference only**:
- User uploads an image.
- Django sends the image to a remote model API endpoint.
- Django shows returned model output + Grad-CAM visualization.
- No local grading/color/size/ripeness scoring is used in the UI flow now.

Main files:
- Django client/service: `products/quality_inspection.py`
- Producer inspection view/form: `products/views_frontend.py`
- Inspection template: `templates/pages/producer/producer_quality_inspection.html`
- Model API server (FastAPI): `ml/model_api_server.py`

## API Contract in Use

Django currently expects/handles model API output like:
- `label`
- `confidence` and/or `confidence_percent`
- `gradcam` (data URI) or `gradcam_base64` or `gradcam_image_url`
- optional `freshness_label`
- optional `assessed_by_model` / `model_name`
- optional `explanation`

Upload field sent by Django to API:
- `file` (multipart)

Configured from Django settings/env:
- `QUALITY_MODEL_API_URL`
- `QUALITY_MODEL_API_KEY`
- `QUALITY_MODEL_AUTH_HEADER`
- `QUALITY_MODEL_API_TIMEOUT_SECONDS`

## FastAPI Server Notes

`ml/model_api_server.py` is currently based on the provided reference `api.py` pattern:
- YOLO classification inference
- Grad-CAM generation
- `/predict` endpoint with image upload
- optional `/recommend` endpoint assets
- `web/` static mount is conditional (won't crash if folder missing)

Important env used by API server:
- `MODEL_PATH`
- `IMAGE_SIZE`
- recommendation-related env vars (if `/recommend` used)

## Important Context / Constraints

- The repository has evolved; some older quality-inspection model/database fields still exist for backward compatibility, but active UX now focuses on direct model inference output.
- If classification differs across environments, likely causes are:
  - different preprocessing/runtime versions
  - different effective model file
  - different endpoint code path
- Keep request/response contract stable when changing either Django client or FastAPI server.

## Recommended Next Cleanup (Optional)

- Remove or refactor unused legacy quality scoring/DB paths if full migration to pure inference-only workflow is desired.
- Add explicit API schema validation in Django client for safer error handling.
- Pin exact ML package versions across environments for reproducible predictions.

# Recommendation System Architecture

## Purpose

The recommendation system predicts products a customer is likely to reorder based on historical shopping behavior.

The goal is to:
- improve user convenience
- support recurring grocery purchases
- increase user engagement
- integrate with the food freshness workflow

---

# Dataset

The recommendation model is trained using the Instacart Market Basket dataset.

Relevant files:
- orders.csv
- products.csv
- order_products__train.csv

Merged using:
- order_id
- product_id

The final processed dataset contains:
- user purchase history
- reorder behavior
- engineered behavioral features

---

# Recommendation Model

Model Type:
- XGBoost Classifier

Saved Model File:
- models/recommendation_model.pkl

Prediction Target:
- reordered (0 or 1)

The model predicts:
- reorder probability
- top likely products for a user

---

# Feature Engineering

The recommendation system uses behavioral features derived from transaction history.

Current features:

## purchase_count
Number of times a user purchased a product.

## avg_cart_position
Average order position in shopping cart.

## avg_days_between_orders
Average reorder interval.

## product_popularity
Global purchase frequency.

## user_total_orders
Total number of user orders.

IMPORTANT:
- Prevent data leakage.
- Never engineer features using future reorder information.
- Features must be computable at inference time.

---

# Recommendation Pipeline

## Offline Training Flow

Raw Transaction Data
→ Feature Engineering
→ Train/Test Split
→ XGBoost Training
→ Evaluation
→ Save recommendation_model.pkl

---

# Runtime Recommendation Flow

User Visits Website
→ Load User Purchase History
→ Compute Features
→ Load recommendation_model.pkl
→ Predict Reorder Probabilities
→ Rank Products
→ Return Top-N Recommendations

---

# Django Integration

The recommendation system should integrate into Django server-side views.

Main integration goals:
- show personalized product recommendations
- support recurring order suggestions
- support reorder recommendations

Potential integration locations:
- homepage
- cart page
- checkout page
- producer dashboard

---

# Backend Recommendation Service

Recommendation logic should be isolated into a service layer.

Recommended file:
- products/recommendation_service.py

Responsibilities:
- load trained model
- compute inference features
- generate predictions
- rank products
- return serialized recommendation results

Avoid embedding ML logic directly in views.

---

# Recommendation API Contract

Recommended response format:

{
  "user_id": 123,
  "recommendations": [
    {
      "product_id": 42,
      "product_name": "Organic Banana",
      "probability": 0.93
    }
  ]
}

---

# Recommendation Ranking Logic

Recommendations should:
- rank by reorder probability
- return top-N products
- optionally exclude recently purchased items
- optionally filter unavailable products

Default:
- return top 5 recommendations

---

# Explainable AI

Use SHAP for explainability.

Goals:
- identify important behavioral features
- explain why products were recommended

Possible explanation examples:
- frequently reordered
- commonly purchased together
- short reorder interval

Explainability outputs may later be shown in producer/admin analytics.

---

# Model Loading Requirements

The trained model should:
- load once on startup
- be cached in memory
- avoid reloading per request

Recommended:
- singleton service pattern
- module-level cached model

---

# Performance Constraints

The recommendation system should:
- respond quickly (<500ms preferred)
- avoid recomputing expensive aggregations repeatedly
- support future scaling

Prefer:
- precomputed user-product features
- cached recommendation candidates

---

# Future Expansion Ideas

Potential future upgrades:
- collaborative filtering
- hybrid recommendation models
- embeddings/vector similarity
- real-time recommendation updates
- cross-user similarity recommendations
- session-based recommendations

---

# Development Constraints

- Follow Django architecture conventions.
- Keep recommendation logic modular.
- Avoid hardcoded file paths.
- Keep inference deterministic.
- Preserve existing navigation/UI structure.
- Do not break current quality inspection flow.