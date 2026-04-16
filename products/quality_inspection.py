from __future__ import annotations

import colorsys
import json
import math
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from PIL import Image, ImageStat


SUPPORTED_PRODUCE = {
    "apple": ("apple", "apples"),
    "banana": ("banana", "bananas"),
    "bellpepper": ("bellpepper", "bell pepper", "bell_pepper", "capsicum"),
    "grape": ("grape", "grapes"),
    "guava": ("guava", "guavas"),
    "jujube": ("jujube", "jujubes"),
    "mango": ("mango", "mangoes", "mangos"),
    "orange": ("orange", "oranges"),
    "tomato": ("tomato", "tomatoes"),
    "carrot": ("carrot", "carrots"),
    "cucumber": ("cucumber", "cucumbers"),
}

MODEL_LABELS_12 = [
    "healthy_apple",
    "rotten_apple",
    "healthy_banana",
    "rotten_banana",
    "healthy_orange",
    "rotten_orange",
    "healthy_tomato",
    "rotten_tomato",
    "healthy_carrot",
    "rotten_carrot",
    "healthy_cucumber",
    "rotten_cucumber",
]
MODEL_PRODUCE_LABELS = list(SUPPORTED_PRODUCE.keys())


@dataclass
class FreshnessResult:
    produce_type: str
    freshness_label: str
    confidence: float
    model_name: str


@dataclass
class QualityInspectionResult:
    produce_type: str
    freshness_label: str
    freshness_confidence: float
    color_score: int
    size_score: int
    ripeness_score: int
    overall_grade: str
    suggested_action: str
    explanation: str
    assessed_by_model: str


def _clamp(score: float) -> int:
    return max(0, min(100, int(round(score))))


def _infer_produce_type(name: str) -> str:
    normalized = (name or "").strip().lower()
    for produce_type, variants in SUPPORTED_PRODUCE.items():
        if any(token in normalized for token in variants):
            return produce_type
    return ""


def _normalize_produce_token(value: str) -> str:
    normalized = (value or "").strip().lower().replace("-", " ").replace("_", " ")
    normalized = " ".join(normalized.split())
    for produce_type, variants in SUPPORTED_PRODUCE.items():
        if normalized == produce_type or normalized in variants:
            return produce_type
    collapsed = normalized.replace(" ", "")
    for produce_type, variants in SUPPORTED_PRODUCE.items():
        variant_tokens = {produce_type, *(variant.replace(" ", "") for variant in variants)}
        if collapsed in variant_tokens:
            return produce_type
    return normalized.replace(" ", "_")


def _open_image(image_source) -> Image.Image:
    if hasattr(image_source, "open"):
        image_source.open("rb")
    return Image.open(image_source).convert("RGB")


def _background_reference(image: Image.Image) -> tuple[int, int, int]:
    width, height = image.size
    patch = max(8, min(width, height) // 10)
    corners = [
        image.crop((0, 0, patch, patch)),
        image.crop((width - patch, 0, width, patch)),
        image.crop((0, height - patch, patch, height)),
        image.crop((width - patch, height - patch, width, height)),
    ]
    rgb_totals = [0.0, 0.0, 0.0]
    for corner in corners:
        stat = ImageStat.Stat(corner)
        for idx, value in enumerate(stat.mean[:3]):
            rgb_totals[idx] += value
    return tuple(int(value / len(corners)) for value in rgb_totals)


def _extract_subject_pixels(image: Image.Image) -> list[tuple[int, int, int]]:
    background = _background_reference(image)
    pixels = list(image.getdata())
    subject_pixels = []
    for pixel in pixels:
        distance = math.sqrt(sum((pixel[idx] - background[idx]) ** 2 for idx in range(3)))
        if distance > 42:
            subject_pixels.append(pixel)
    return subject_pixels if subject_pixels else pixels


def _score_color(subject_pixels: list[tuple[int, int, int]]) -> int:
    hsv_values = [colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0) for r, g, b in subject_pixels]
    avg_saturation = sum(hsv[1] for hsv in hsv_values) / len(hsv_values)
    avg_brightness = sum(hsv[2] for hsv in hsv_values) / len(hsv_values)
    hue_values = [hsv[0] for hsv in hsv_values]
    hue_spread = max(hue_values) - min(hue_values) if hue_values else 0.0
    uniformity = max(0.0, 1.0 - min(1.0, hue_spread * 1.8))
    score = (avg_saturation * 42.0) + (avg_brightness * 33.0) + (uniformity * 25.0)
    return _clamp(score)


def _score_size(image: Image.Image, subject_pixels: list[tuple[int, int, int]]) -> int:
    subject_ratio = len(subject_pixels) / max(1, image.size[0] * image.size[1])
    ideal_ratio = 0.42
    deviation = abs(subject_ratio - ideal_ratio)
    score = 100.0 - min(100.0, (deviation / ideal_ratio) * 100.0)
    return _clamp(score)


def _produce_hue_score(produce_type: str, hsv_values: list[tuple[float, float, float]]) -> float:
    if not hsv_values:
        return 50.0

    avg_hue = sum(hsv[0] for hsv in hsv_values) / len(hsv_values)
    hue_degrees = avg_hue * 360.0
    targets = {
        "apple": 5.0,
        "banana": 52.0,
        "orange": 32.0,
        "tomato": 6.0,
        "carrot": 28.0,
        "cucumber": 118.0,
    }
    target = targets.get(produce_type, 45.0)
    distance = min(abs(hue_degrees - target), 360.0 - abs(hue_degrees - target))
    return max(20.0, 100.0 - (distance / 90.0) * 100.0)


def _score_ripeness(produce_type: str, subject_pixels: list[tuple[int, int, int]], freshness_confidence: float) -> int:
    hsv_values = [colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0) for r, g, b in subject_pixels]
    avg_saturation = sum(hsv[1] for hsv in hsv_values) / len(hsv_values)
    avg_brightness = sum(hsv[2] for hsv in hsv_values) / len(hsv_values)
    hue_score = _produce_hue_score(produce_type, hsv_values)
    freshness_score = max(0.0, min(100.0, freshness_confidence))
    score = (freshness_score * 0.45) + (hue_score * 0.3) + (avg_saturation * 100.0 * 0.15) + (avg_brightness * 100.0 * 0.1)
    return _clamp(score)


def _grade_from_scores(color_score: int, size_score: int, ripeness_score: int) -> str:
    if color_score < 65 or size_score < 70 or ripeness_score < 60:
        return "C"
    if color_score < 75 or size_score < 80 or ripeness_score < 70:
        return "B"
    return "A"


def _suggested_action(grade: str, stock_quantity: int) -> str:
    if grade == "A":
        return "Keep standard pricing and prioritize normal sale."
    if grade == "B":
        if stock_quantity > 20:
            return "Apply a light discount and promote as near-peak stock."
        return "Sell soon and monitor freshness daily."
    if stock_quantity > 10:
        return "Apply a stronger discount or route to surplus/community sale immediately."
    return "Use for rapid sale, donation, or remove from premium listing."


def _build_explanation(color_score: int, size_score: int, ripeness_score: int, freshness_label: str) -> str:
    return (
        f"Color {color_score}%, Size {size_score}%, Ripeness {ripeness_score}%."
        f" Freshness signal indicates {freshness_label}. Grade follows assignment thresholds."
    )


def _normalize_freshness_label(label: str) -> str:
    normalized = (label or "").strip().lower()
    if normalized in {"healthy", "fresh"}:
        return "fresh"
    if normalized == "rotten":
        return "rotten"
    return "unknown"


def _classifier_labels_path() -> Path:
    return Path(settings.BASE_DIR) / "weights" / "fruit_vegetable_classifier_labels.json"


def _load_classifier_metadata() -> dict:
    labels_path = _classifier_labels_path()
    if not labels_path.exists():
        return {}

    try:
        raw_data = json.loads(labels_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    return raw_data if isinstance(raw_data, dict) else {"labels": raw_data}


def _load_classifier_labels() -> list[str]:
    raw_data = _load_classifier_metadata()
    if not raw_data:
        return []

    if isinstance(raw_data, dict):
        if "class_indices" in raw_data and isinstance(raw_data["class_indices"], dict):
            return [label for label, _ in sorted(raw_data["class_indices"].items(), key=lambda item: int(item[1]))]
        if "labels" in raw_data and isinstance(raw_data["labels"], list):
            return [str(label) for label in raw_data["labels"]]

    if isinstance(raw_data, list):
        return [str(label) for label in raw_data]

    return []


def _parse_classifier_label(label: str) -> tuple[str, str]:
    raw_label = (label or "").strip()
    if not raw_label:
        return "", "unknown"

    normalized = raw_label.replace("-", "_").replace("__", "_")
    parts = [part for part in normalized.split("_") if part]
    if len(parts) >= 2:
        freshness_candidates = {_normalize_freshness_label(part) for part in parts}
        freshness_label = next((candidate for candidate in freshness_candidates if candidate != "unknown"), "unknown")
        produce_parts = [part for part in parts if _normalize_freshness_label(part) == "unknown"]
        produce_type = _normalize_produce_token("_".join(produce_parts)) if produce_parts else ""
        return produce_type, freshness_label

    return _normalize_produce_token(raw_label), "unknown"


def _predict_classifier_with_keras(image: Image.Image, produce_type_hint: str) -> FreshnessResult | None:
    model_path = Path(settings.BASE_DIR) / "weights" / "fruit_vegetable_classifier.h5"
    try:
        from .models import AIModelVersion

        active_model = (
            AIModelVersion.objects.filter(task_type="quality_freshness", is_active=True)
            .order_by("-activated_at", "-created_at")
            .first()
        )
        if active_model and active_model.artifact:
            model_path = Path(active_model.artifact.path)
    except Exception:
        pass

    if not model_path.exists():
        return None

    try:
        import tensorflow as tf
        from tensorflow.keras.applications.efficientnet import preprocess_input
    except Exception:
        return None

    classifier_metadata = _load_classifier_metadata()
    image_size = int(classifier_metadata.get("image_size", 224)) if classifier_metadata else 224
    resized = image.resize((image_size, image_size))
    tensor = tf.keras.utils.img_to_array(resized)
    tensor = tf.expand_dims(tensor, axis=0)
    tensor = preprocess_input(tensor)

    model = tf.keras.models.load_model(model_path)
    predictions = model.predict(tensor, verbose=0)
    if isinstance(predictions, dict):
        output = next(iter(predictions.values()))[0]
    else:
        output = predictions[0]

    classifier_labels = _load_classifier_labels()
    if classifier_labels and len(output) == len(classifier_labels):
        best_index = max(range(len(output)), key=lambda idx: float(output[idx]))
        produce_type, freshness_label = _parse_classifier_label(classifier_labels[best_index])
        return FreshnessResult(
            produce_type=produce_type or produce_type_hint,
            freshness_label=freshness_label,
            confidence=max(0.0, min(100.0, float(output[best_index]) * 100.0)),
            model_name="fruit_vegetable_classifier.h5",
        )

    if len(output) == 2:
        best_index = max(range(len(output)), key=lambda idx: float(output[idx]))
        predicted_label = ("fresh", "rotten")[best_index]
        return FreshnessResult(
            produce_type=produce_type_hint,
            freshness_label=_normalize_freshness_label(predicted_label),
            confidence=max(0.0, min(100.0, float(output[best_index]) * 100.0)),
            model_name="fruit_vegetable_classifier.h5",
        )

    if len(output) == len(MODEL_PRODUCE_LABELS):
        best_index = max(range(len(output)), key=lambda idx: float(output[idx]))
        return FreshnessResult(
            produce_type=MODEL_PRODUCE_LABELS[best_index],
            freshness_label="unknown",
            confidence=max(0.0, min(100.0, float(output[best_index]) * 100.0)),
            model_name="fruit_vegetable_classifier.h5",
        )

    if len(output) == len(MODEL_LABELS_12):
        best_index = max(range(len(output)), key=lambda idx: float(output[idx]))
        best_label = MODEL_LABELS_12[best_index]
        health_label, produce_type = best_label.split("_", 1)
        return FreshnessResult(
            produce_type=produce_type,
            freshness_label=_normalize_freshness_label(health_label),
            confidence=max(0.0, min(100.0, float(output[best_index]) * 100.0)),
            model_name="fruit_vegetable_classifier.h5",
        )

    return None


def inspect_product_quality(product, image_source) -> QualityInspectionResult:
    produce_type_hint = _infer_produce_type(product.name) or _infer_produce_type(product.category.name)
    image = _open_image(image_source)
    subject_pixels = _extract_subject_pixels(image)

    classifier_result = _predict_classifier_with_keras(image, produce_type_hint)
    color_score = _score_color(subject_pixels)
    if classifier_result is None:
        freshness_confidence = 82.0 if color_score >= 65 else 58.0
        freshness = FreshnessResult(
            produce_type=produce_type_hint,
            freshness_label="fresh" if freshness_confidence >= 65 else "rotten",
            confidence=freshness_confidence,
            model_name="heuristic_quality_pipeline",
        )
    elif classifier_result.freshness_label == "unknown":
        freshness_confidence = 82.0 if color_score >= 65 else 58.0
        freshness = FreshnessResult(
            produce_type=classifier_result.produce_type or produce_type_hint,
            freshness_label="fresh" if freshness_confidence >= 65 else "rotten",
            confidence=freshness_confidence,
            model_name=f"{classifier_result.model_name} + heuristic_quality_pipeline",
        )
    else:
        freshness = classifier_result

    produce_type = freshness.produce_type or produce_type_hint or "unknown"

    size_score = _score_size(image, subject_pixels)
    ripeness_score = _score_ripeness(produce_type, subject_pixels, freshness.confidence)
    overall_grade = _grade_from_scores(color_score, size_score, ripeness_score)
    suggested_action = _suggested_action(overall_grade, product.stock_quantity)
    explanation = _build_explanation(color_score, size_score, ripeness_score, freshness.freshness_label)

    return QualityInspectionResult(
        produce_type=produce_type,
        freshness_label=freshness.freshness_label,
        freshness_confidence=round(freshness.confidence, 2),
        color_score=color_score,
        size_score=size_score,
        ripeness_score=ripeness_score,
        overall_grade=overall_grade,
        suggested_action=suggested_action,
        explanation=explanation,
        assessed_by_model=freshness.model_name,
    )
