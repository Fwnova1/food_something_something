              # ML Runtime

This folder separates ML dependencies from the Django app runtime.

## Why

The current project runtime is not able to execute `.keras` models because the active Python is `3.14` and TensorFlow is not installed. The Django app already falls back to heuristic scoring when TensorFlow is unavailable. This ML folder is the supported path for real inference and training.

Official TensorFlow Windows install guidance: https://www.tensorflow.org/install/pip

## Recommended inference environment

Use Python `3.11.x` 64-bit in a dedicated virtual environment.

Example:

```powershell
cd e:\123123\food_something_something-main
py -3.11 -m venv .venv-ml
.venv-ml\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r ml\requirements.inference.txt
python ml\check_inference_env.py
```

If that succeeds, the Django quality inspection service can use:

- `weights/fruit_vegetable_classifier.h5`
- `weights/quality_multi_output_model.keras`
- `weights/quality_multi_output_metadata.json`

## Train a new multi-output quality model

You need a CSV with these columns:

- `image_path`
- `produce_type`
- `freshness_label`
- `color_score`
- `size_score`
- `ripeness_score`
- `grade`

### Bootstrap labels from the current healthy/rotten dataset

If your dataset only contains folder labels like `healthy apple` and `rotten banana`, bootstrap a weakly-labeled CSV first:

```powershell
python ml\bootstrap_quality_labels.py --dataset-root E:\datasets\fruit-veg --output-csv artifacts\quality_labels.csv
```

This is only a starting point. For better results, manually review the generated `color_score`, `size_score`, `ripeness_score`, and `grade`.

### Train

```powershell
pip install -r ml\requirements.training.txt
python ml\train_quality_model.py ^
  --labels-csv artifacts\quality_labels.csv ^
  --output-model weights\quality_multi_output_model.keras ^
  --output-metadata weights\quality_multi_output_metadata.json ^
  --epochs 15
```

## Remote model API server (FastAPI)

The Django app now calls a remote API for quality inspection.

Run model server:

```powershell
cd C:\Users\admin\Desktop\food_something_something
python -m pip install -r ml\requirements.inference.txt
$env:QUALITY_MODEL_PATH="C:/Users/admin/Desktop/Asd_project/runs/classify/train4/weights/best.pt"
$env:QUALITY_MODEL_API_KEY="your-secret-key"
uvicorn ml.model_api_server:app --host 0.0.0.0 --port 8001
```

Health check:

```powershell
curl http://127.0.0.1:8001/health
```

Prediction endpoint:

- `POST /predict`
- Form-data:
  - `image` (file, required)
  - `produce_type_hint` (text, optional)
- Header:
  - `X-API-Key` (required if `QUALITY_MODEL_API_KEY` is set on the server)

Response keys used by Django:

- `produce_type`
- `freshness_label` (`fresh`/`rotten`/`unknown`)
- `freshness_confidence` (0-100)
- `color_score`
- `size_score`
- `ripeness_score`
- `overall_grade` (`A`/`B`/`C`)
- `suggested_action`
- `explanation`
- `assessed_by_model`
- `gradcam_base64` (preferred if URL is not provided)
- `gradcam_image_url` (optional)

Django settings side:

```powershell
$env:QUALITY_MODEL_API_URL="http://127.0.0.1:8001/predict"
$env:QUALITY_MODEL_API_KEY="your-secret-key"
$env:QUALITY_MODEL_AUTH_HEADER="X-API-Key"
$env:QUALITY_MODEL_API_TIMEOUT_SECONDS="45"
```
