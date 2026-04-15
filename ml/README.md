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

- `weights/fruit_fresh_rotten_model.keras`
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

### Bootstrap labels from the current fresh/rotten dataset

If your dataset only contains folder labels like `fresh apple` and `rotten banana`, bootstrap a weakly-labeled CSV first:

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

## What the Django app will do

`products/quality_inspection.py` follows this order:

1. Try `weights/quality_multi_output_model.keras` plus metadata JSON.
2. Otherwise try `weights/fruit_fresh_rotten_model.keras` for freshness only.
3. Otherwise fall back to heuristic image analysis.

That means once you place the trained multi-output model in `weights/`, the app can use it without further code changes.
