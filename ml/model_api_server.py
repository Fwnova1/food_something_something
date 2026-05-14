import base64
import io
import json
import os
from pathlib import Path
from typing import Tuple

import cv2
import joblib
import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from PIL import Image
from ultralytics import YOLO

MODEL_PATH = os.getenv(
    "MODEL_PATH",
    "C:/Users/admin/Desktop/Asd_project/runs/classify/train4/weights/best.pt",
)
IMAGE_SIZE = int(os.getenv("IMAGE_SIZE", "224"))
RECOMMENDATION_MODEL_PATH = os.getenv(
    "RECOMMENDATION_MODEL_PATH",
    r"C:/Users/admin/Desktop/aiminh/recommendation_model.pkl",
)
RECOMMENDATION_FEATURES_PATH = os.getenv("RECOMMENDATION_FEATURES_PATH", "advanced_processed_data.csv")
RECOMMENDATION_SOURCE_PATH = os.getenv("RECOMMENDATION_SOURCE_PATH", "merged_data.csv")
RECOMMENDATION_FEATURE_COLUMNS = [
    "avg_cart_position",
    "avg_days_between_orders",
    "product_popularity",
    "user_total_orders",
]

app = FastAPI(title="Fruit Classifier API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_model: YOLO | None = None
_model_loaded_from: str = ""
_recommendation_model = None
_recommendation_model_loaded_from: str = ""
_recommendation_features: pd.DataFrame | None = None
_product_lookup: pd.DataFrame | None = None


def get_project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def get_quality_model_config_path() -> Path:
    return get_project_root() / "weights" / "quality_models" / "active_quality_model.json"


def resolve_quality_model_path() -> Path:
    """
    Resolution order:
    1) Admin-selected model from manager page config JSON.
    2) MODEL_PATH environment variable.
    """
    config_path = get_quality_model_config_path()
    if config_path.exists():
        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
            active_model_name = str(raw.get("active_model", "")).strip()
            if active_model_name:
                candidate = (config_path.parent / active_model_name).resolve()
                if candidate.exists():
                    return candidate
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass
    return Path(MODEL_PATH).resolve()


def get_recommendation_model_config_path() -> Path:
    return get_project_root() / "weights" / "uploaded_recommendation_models" / "active_recommendation_model.json"


def resolve_recommendation_model_path() -> Path:
    """
    Resolution order:
    1) Admin-selected recommendation model from config JSON.
    2) RECOMMENDATION_MODEL_PATH environment variable.
    """
    config_path = get_recommendation_model_config_path()
    if config_path.exists():
        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
            active_model_name = str(raw.get("active_model", "")).strip()
            if active_model_name:
                candidate = (config_path.parent / active_model_name).resolve()
                if candidate.exists():
                    return candidate
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass
    return Path(RECOMMENDATION_MODEL_PATH).resolve()


def get_recommendation_model():
    global _recommendation_model, _recommendation_model_loaded_from
    model_file = resolve_recommendation_model_path()
    if not model_file.exists():
        raise FileNotFoundError(f"Recommendation model file not found: {model_file}")
    resolved = str(model_file)
    if _recommendation_model is None or _recommendation_model_loaded_from != resolved:
        _recommendation_model = joblib.load(model_file)
        _recommendation_model_loaded_from = resolved
    return _recommendation_model


def get_model() -> YOLO:
    global _model, _model_loaded_from
    model_file = resolve_quality_model_path()
    if not model_file.exists():
        raise FileNotFoundError(f"Model file not found: {model_file}")

    resolved = str(model_file)
    if _model is None or _model_loaded_from != resolved:
        _model = YOLO(resolved)
        _model_loaded_from = resolved
    return _model


def get_recommendation_assets():
    global _recommendation_model, _recommendation_features, _product_lookup

    if _recommendation_model is None:
        _recommendation_model = get_recommendation_model()

    if _recommendation_features is None:
        features_file = Path(RECOMMENDATION_FEATURES_PATH)
        if not features_file.exists():
            raise FileNotFoundError(f"Recommendation features file not found: {features_file}")
        _recommendation_features = pd.read_csv(features_file)

    if _product_lookup is None:
        source_file = Path(RECOMMENDATION_SOURCE_PATH)
        if not source_file.exists():
            raise FileNotFoundError(f"Recommendation source file not found: {source_file}")
        raw = pd.read_csv(source_file, usecols=["product_id", "product_name"])
        _product_lookup = raw.drop_duplicates(subset=["product_id"]).reset_index(drop=True)

    return _recommendation_model, _recommendation_features, _product_lookup


class RecommendRequest(BaseModel):
    user_id: int
    top_k: int = 5
    candidates: list[dict] | None = None


def build_xai_for_row(row: pd.Series, feature_weights: dict[str, float], feature_max: dict[str, float]) -> tuple[str, list[dict]]:
    contributions = []
    for feature in RECOMMENDATION_FEATURE_COLUMNS:
        raw_value = float(row.get(feature, 0.0) or 0.0)
        max_value = max(1e-9, float(feature_max.get(feature, 1.0)))
        normalized = raw_value / max_value
        weight = float(feature_weights.get(feature, 0.0))
        contribution = normalized * weight
        contributions.append(
            {
                "feature": feature,
                "value": round(raw_value, 4),
                "weight": round(weight, 6),
                "contribution": round(contribution, 6),
            }
        )

    contributions.sort(key=lambda item: abs(item["contribution"]), reverse=True)
    top = contributions[:2]

    feature_labels = {
        "avg_cart_position": "cart-position pattern",
        "avg_days_between_orders": "reorder timing pattern",
        "product_popularity": "overall product popularity",
        "user_total_orders": "your order history depth",
    }
    reasons = [feature_labels.get(item["feature"], item["feature"]) for item in top]
    summary = "Recommended due to " + " and ".join(reasons) + "."
    return summary, top


def get_last_conv_layer(module: torch.nn.Module) -> torch.nn.Module:
    last_conv = None
    for child in module.modules():
        if isinstance(child, torch.nn.Conv2d):
            last_conv = child
    if last_conv is None:
        raise RuntimeError("No Conv2d layer found for Grad-CAM generation.")
    return last_conv


def preprocess(image: Image.Image, device: torch.device) -> Tuple[torch.Tensor, np.ndarray]:
    rgb = image.convert("RGB")
    resized = rgb.resize((IMAGE_SIZE, IMAGE_SIZE))
    image_np = np.array(resized)
    tensor = torch.from_numpy(image_np).permute(2, 0, 1).float() / 255.0
    tensor = tensor.unsqueeze(0).to(device)
    return tensor, image_np


def analyze_size_and_color(image: Image.Image) -> dict:
    """
    Lightweight OpenCV heuristics:
    - Segment foreground object from near-white background.
    - Size score from relative contour area.
    - Color score from saturation/brightness consistency.
    Returns normalized 0..100 scores with coarse labels.
    """
    rgb = np.array(image.convert("RGB"))
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)

    # Foreground mask: keep colored regions, suppress very low-sat background.
    sat = hsv[:, :, 1]
    val = hsv[:, :, 2]
    fg_mask = cv2.inRange(hsv, (0, 30, 20), (179, 255, 255))
    fg_mask = cv2.medianBlur(fg_mask, 5)
    kernel = np.ones((5, 5), np.uint8)
    fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv2.findContours(fg_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    image_area = float(rgb.shape[0] * rgb.shape[1]) or 1.0

    if contours:
        largest = max(contours, key=cv2.contourArea)
        fruit_area = float(cv2.contourArea(largest))
    else:
        fruit_area = 0.0

    area_ratio = max(0.0, min(1.0, fruit_area / image_area))
    # Heuristic: fruit occupying >=40% image gets max score.
    size_score = max(0.0, min(100.0, (area_ratio / 0.40) * 100.0))

    fg_indices = fg_mask > 0
    if np.any(fg_indices):
        sat_vals = sat[fg_indices].astype(np.float32)
        val_vals = val[fg_indices].astype(np.float32)
        sat_mean = float(np.mean(sat_vals))
        val_mean = float(np.mean(val_vals))
        sat_std = float(np.std(sat_vals))
        val_std = float(np.std(val_vals))
    else:
        sat_mean = val_mean = sat_std = val_std = 0.0

    # Color quality favors vivid but not noisy colors.
    # Higher saturation/brightness, lower variance => higher score.
    vividness = 0.6 * (sat_mean / 255.0) + 0.4 * (val_mean / 255.0)
    stability_penalty = min(0.35, (sat_std / 255.0) * 0.2 + (val_std / 255.0) * 0.15)
    color_score = max(0.0, min(100.0, (vividness - stability_penalty) * 100.0))

    def to_grade(score: float) -> str:
        if score >= 80.0:
            return "A"
        if score >= 60.0:
            return "B"
        return "C"

    return {
        "size_score": round(size_score, 2),
        "color_score": round(color_score, 2),
        "size_grade": to_grade(size_score),
        "color_grade": to_grade(color_score),
        "foreground_area_ratio": round(area_ratio, 4),
    }


def _label_indicates_rotten(label: str) -> bool:
    normalized = str(label or "").strip().lower().replace("-", "_").replace(" ", "_")
    return normalized.endswith("_rotten") or normalized == "rotten"


def generate_gradcam(model: YOLO, image: Image.Image, class_idx: int) -> str:
    net = model.model
    net.eval()
    device = next(net.parameters()).device
    for param in net.parameters():
        param.requires_grad_(True)

    input_tensor, image_np = preprocess(image, device)
    input_tensor = input_tensor.requires_grad_(True)

    activations = []
    gradients = []

    target_layer = get_last_conv_layer(net)

    def forward_hook(_module, _in, out):
        activations.append(out.clone())
        out.register_hook(lambda grad: gradients.append(grad.clone()))

    f_handle = target_layer.register_forward_hook(forward_hook)

    try:
        with torch.enable_grad():
            logits = net(input_tensor)
            if isinstance(logits, (tuple, list)):
                logits = logits[0]

            if not isinstance(logits, torch.Tensor):
                raise RuntimeError("Classifier forward pass did not return a tensor.")
            if not logits.requires_grad:
                raise RuntimeError("Classifier logits are detached from gradient graph.")

            score = logits[:, class_idx].sum()
            net.zero_grad(set_to_none=True)
            score.backward()

        if not activations or not gradients:
            raise RuntimeError("Unable to compute Grad-CAM hooks.")

        activation = activations[0][0]
        gradient = gradients[0][0]

        weights = gradient.mean(dim=(1, 2), keepdim=True)
        cam = (weights * activation).sum(dim=0)
        cam = F.relu(cam)

        cam = cam.detach().cpu().numpy()
        cam = (cam - cam.min()) / (cam.max() - cam.min() + 1e-8)
        cam = cv2.resize(cam, (image_np.shape[1], image_np.shape[0]))

        heatmap = np.uint8(255 * cam)
        heatmap = cv2.applyColorMap(heatmap, cv2.COLORMAP_JET)
        heatmap = cv2.cvtColor(heatmap, cv2.COLOR_BGR2RGB)

        overlay = (0.45 * heatmap + 0.55 * image_np).astype(np.uint8)

        buffer = io.BytesIO()
        Image.fromarray(overlay).save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
        return f"data:image/png;base64,{encoded}"
    finally:
        f_handle.remove()


@app.get("/")
def home() -> FileResponse:
    return FileResponse("web/index.html")


@app.get("/health")
def health() -> dict:
    model = get_model()
    return {"status": "ok", "model": _model_loaded_from or str(resolve_quality_model_path()), "classes": model.names}


@app.post("/predict")
async def predict(file: UploadFile = File(...)) -> dict:
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Please upload an image file.")

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file uploaded.")

    try:
        image = Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid image file: {exc}") from exc

    model = get_model()

    results = model.predict(source=image, imgsz=IMAGE_SIZE, verbose=False)
    result = results[0]

    if result.probs is None:
        raise HTTPException(status_code=500, detail="Model did not return classification probabilities.")

    top1 = int(result.probs.top1)
    confidence = float(result.probs.top1conf.item())
    freshness_confidence_percent = round(confidence * 100.0, 2)
    label = result.names[top1]
    quality_metrics = analyze_size_and_color(image)
    blended_score = (0.5 * freshness_confidence_percent) + (0.25 * quality_metrics["size_score"]) + (0.25 * quality_metrics["color_score"])
    if _label_indicates_rotten(label):
        overall_grade = "C"
    elif blended_score >= 80.0:
        overall_grade = "A"
    elif blended_score >= 60.0:
        overall_grade = "B"
    else:
        overall_grade = "C"

    try:
        gradcam = generate_gradcam(model, image, top1)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Grad-CAM generation failed: {exc}") from exc

    return {
        "label": label,
        "freshness_label": "rotten" if _label_indicates_rotten(label) else label,
        "freshness_confidence": freshness_confidence_percent,
        "confidence": confidence,
        "confidence_percent": freshness_confidence_percent,
        "class_index": top1,
        "size_score": quality_metrics["size_score"],
        "color_score": quality_metrics["color_score"],
        "size_grade": quality_metrics["size_grade"],
        "color_grade": quality_metrics["color_grade"],
        "overall_grade": "F" if _label_indicates_rotten(label) else overall_grade,
        "analysis_meta": {
            "foreground_area_ratio": quality_metrics["foreground_area_ratio"],
        },
        "gradcam": gradcam,
    }


@app.post("/recommend")
def recommend(request: RecommendRequest) -> dict:
    model = get_recommendation_model()

    top_k = max(1, min(int(request.top_k), 20))

    if request.candidates:
        candidates_df = pd.DataFrame(request.candidates).copy()
        for col in RECOMMENDATION_FEATURE_COLUMNS:
            if col not in candidates_df.columns:
                candidates_df[col] = 0.0

        if hasattr(model, "predict_proba"):
            scores = model.predict_proba(candidates_df[RECOMMENDATION_FEATURE_COLUMNS])[:, 1]
        else:
            scores = model.predict(candidates_df[RECOMMENDATION_FEATURE_COLUMNS])

        raw_importances = getattr(model, "feature_importances_", None)
        if raw_importances is not None and len(raw_importances) == len(RECOMMENDATION_FEATURE_COLUMNS):
            feature_weights = {
                RECOMMENDATION_FEATURE_COLUMNS[idx]: float(raw_importances[idx]) for idx in range(len(RECOMMENDATION_FEATURE_COLUMNS))
            }
        else:
            uniform = 1.0 / len(RECOMMENDATION_FEATURE_COLUMNS)
            feature_weights = {col: uniform for col in RECOMMENDATION_FEATURE_COLUMNS}

        feature_max = {
            col: float(candidates_df[col].max() or 0.0) for col in RECOMMENDATION_FEATURE_COLUMNS
        }

        candidates_df["score"] = scores
        ranked = candidates_df.sort_values("score", ascending=False).head(top_k)
        items = []
        for _, row in ranked.iterrows():
            explanation, top_features = build_xai_for_row(row, feature_weights, feature_max)
            items.append(
                {
                    "product_id": int(row["product_id"]),
                    "product_name": str(row["product_name"]) if "product_name" in ranked.columns else f"Product {int(row['product_id'])}",
                    "score": round(float(row["score"]), 6),
                    "reason": "model_score",
                    "explanation": explanation,
                    "xai_top_features": top_features,
                }
            )
        return {
            "user_id": request.user_id,
            "top_k": top_k,
            "used_fallback": False,
            "recommendations": items,
        }

    _model_unused, features_df, product_lookup = get_recommendation_assets()
    user_rows = features_df[features_df["user_id"] == request.user_id].copy()

    if user_rows.empty:
        popular = (
            features_df[["product_id", "product_popularity"]]
            .drop_duplicates(subset=["product_id"])
            .sort_values("product_popularity", ascending=False)
            .head(top_k)
        )
        popular = popular.merge(product_lookup, on="product_id", how="left")
        items = [
            {
                "product_id": int(row.product_id),
                "product_name": row.product_name if pd.notna(row.product_name) else f"Product {int(row.product_id)}",
                "score": None,
                "reason": "popular_fallback",
            }
            for row in popular.itertuples(index=False)
        ]
        return {
            "user_id": request.user_id,
            "top_k": top_k,
            "used_fallback": True,
            "recommendations": items,
        }

    candidate_features = user_rows[RECOMMENDATION_FEATURE_COLUMNS].copy()
    if hasattr(model, "predict_proba"):
        scores = model.predict_proba(candidate_features)[:, 1]
    else:
        scores = model.predict(candidate_features)

    user_rows["score"] = scores
    ranked = user_rows.sort_values("score", ascending=False).head(top_k)
    ranked = ranked.merge(product_lookup, on="product_id", how="left")

    items = [
        {
            "product_id": int(row.product_id),
            "product_name": row.product_name if pd.notna(row.product_name) else f"Product {int(row.product_id)}",
            "score": round(float(row.score), 6),
            "reason": "model_score",
        }
        for row in ranked.itertuples(index=False)
    ]

    return {
        "user_id": request.user_id,
        "top_k": top_k,
        "used_fallback": False,
        "recommendations": items,
    }


if Path("web").exists():
    app.mount("/web", StaticFiles(directory="web"), name="web")
