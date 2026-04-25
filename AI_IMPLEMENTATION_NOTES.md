# AI Implementation Notes

This branch captures the AI work added for the Bristol Regional Food Network case study.

## What was added

- Customer recommendation engine integrated into the product listing page.
- Quick reorder suggestions based on order history.
- Demand forecasting for producer/admin AI insights.
- Quality inspection workflow for fruit and vegetable products.
- A new `QualityInspection` database model and audit trail.
- Heuristic scoring for `Color`, `Size`, and `Ripeness`.
- Grade mapping to `A`, `B`, and `C` using the assignment thresholds.
- Support path for existing `weights/fruit_fresh_rotten_model.keras`.
- ML helper scripts under `ml/` for:
  - inference environment validation
  - bootstrapping quality labels

## Important runtime note

The main Django runtime originally used a Python environment without TensorFlow support, so the quality pipeline included a heuristic fallback. A dedicated ML environment was prepared so `.keras` inference can run when Django is started from that environment.

## Main files touched

- `products/recommendation.py`
- `products/forecasting.py`
- `products/quality_inspection.py`
- `products/views.py`
- `products/views_frontend.py`
- `products/serializers.py`
- `products/models.py`
- `products/urls.py`
- `products/api_urls.py`
- `templates/product_list.html`
- `templates/ai_insights.html`
- `templates/producer_quality_inspection.html`
- `ml/README.md`
- `ml/check_inference_env.py`
- `ml/bootstrap_quality_labels.py`

## Validation completed

- `python manage.py check`
- `python manage.py migrate`
- TensorFlow inference environment check showed the existing `.keras` model loads successfully.
