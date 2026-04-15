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
    "orange": ("orange", "oranges"),
    "tomato": ("tomato", "tomatoes"),
    "carrot": ("carrot", "carrots"),
    "cucumber": ("cucumber", "cucumbers"),
}

MODEL_LABELS_12 = [
    "fresh_apple",
    "rotten_apple",
    "fresh_banana",
    "rotten_banana",
    "fresh_orange",
    "rotten_orange",
    "fresh_tomato",
    "rotten_tomato",
    "fresh_carrot",
    "rotten_carrot",
    "fresh_cucumber",
    "rotten_cucumber",
]


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


def _quality_model_paths() -> tuple[Path, Path]:
    weights_dir = Path(settings.BASE_DIR) / "weights"
    return (
        weights_dir / "quality_multi_output_model.keras",
        weights_dir / "quality_multi_output_metadata.json",
    )


def _predict_multi_output_quality_with_keras(image: Image.Image) -> QualityInspectionResult | None:
    model_path, metadata_path = _quality_model_paths()
    if not model_path.exists() or not metadata_path.exists():
        return None

    try:
        import tensorflow as tf
    except Exception:
        return None

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    image_size = int(metadata.get("image_size", 224))
    produce_labels = metadata.get("produce_labels", [])
    freshness_labels = metadata.get("freshness_labels", ["fresh", "rotten"])
    grade_labels = metadata.get("grade_labels", ["A", "B", "C"])

    resized = image.resize((image_size, image_size))
    tensor = tf.keras.utils.img_to_array(resized)
    tensor = tf.expand_dims(tensor, axis=0) / 255.0

    model = tf.keras.models.load_model(model_path)
    predictions = model.predict(tensor, verbose=0)

    if not isinstance(predictions, dict):
        return None

    produce_logits = predictions.get("produce_type")
    freshness_logits = predictions.get("freshness")
    color_pred = predictions.get("color_score")
    size_pred = predictions.get("size_score")
    ripeness_pred = predictions.get("ripeness_score")
    grade_logits = predictions.get("grade")
    if any(value is None for value in [produce_logits, freshness_logits, color_pred, size_pred, ripeness_pred, grade_logits]):
        return None

    produce_index = int(tf.argmax(produce_logits[0]).numpy())
    freshness_index = int(tf.argmax(freshness_logits[0]).numpy())
    grade_index = int(tf.argmax(grade_logits[0]).numpy())
    produce_type = produce_labels[produce_index] if produce_index < len(produce_labels) else "unknown"
    freshness_label = freshness_labels[freshness_index] if freshness_index < len(freshness_labels) else "unknown"
    freshness_confidence = float(tf.reduce_max(freshness_logits[0]).numpy()) * 100.0
    color_score = _clamp(float(color_pred[0][0]) * 100.0)
    size_score = _clamp(float(size_pred[0][0]) * 100.0)
    ripeness_score = _clamp(float(ripeness_pred[0][0]) * 100.0)
    overall_grade = grade_labels[grade_index] if grade_index < len(grade_labels) else _grade_from_scores(color_score, size_score, ripeness_score)
    suggested_action = _suggested_action(overall_grade, 0)
    explanation = _build_explanation(color_score, size_score, ripeness_score, freshness_label)

    return QualityInspectionResult(
        produce_type=produce_type,
        freshness_label=freshness_label,
        freshness_confidence=round(freshness_confidence, 2),
        color_score=color_score,
        size_score=size_score,
        ripeness_score=ripeness_score,
        overall_grade=overall_grade,
        suggested_action=suggested_action,
        explanation=explanation,
        assessed_by_model=model_path.name,
    )


def _predict_freshness_with_keras(image: Image.Image, produce_type_hint: str) -> FreshnessResult | None:
    model_path = Path(settings.BASE_DIR) / "weights" / "fruit_fresh_rotten_model.keras"
    if not model_path.exists():
        return None

    try:
        import tensorflow as tf
    except Exception:
        return None

    resized = image.resize((224, 224))
    tensor = tf.keras.utils.img_to_array(resized)
    tensor = tf.expand_dims(tensor, axis=0) / 255.0

    model = tf.keras.models.load_model(model_path)
    predictions = model.predict(tensor, verbose=0)
    output = predictions[0]

    if len(output) == 2:
        fresh_confidence = float(output[0]) if output[0] > output[1] else float(1.0 - output[1])
        label = "fresh" if output[0] >= output[1] else "rotten"
        return FreshnessResult(
            produce_type=produce_type_hint,
            freshness_label=label,
            confidence=max(0.0, min(100.0, fresh_confidence * 100.0)),
            model_name="fruit_fresh_rotten_model.keras",
        )

    if len(output) == len(MODEL_LABELS_12):
        best_index = max(range(len(output)), key=lambda idx: float(output[idx]))
        best_label = MODEL_LABELS_12[best_index]
        freshness_label, produce_type = best_label.split("_", 1)
        return FreshnessResult(
            produce_type=produce_type,
            freshness_label=freshness_label,
            confidence=max(0.0, min(100.0, float(output[best_index]) * 100.0)),
            model_name="fruit_fresh_rotten_model.keras",
        )

    return None


def inspect_product_quality(product, image_source) -> QualityInspectionResult:
    produce_type_hint = _infer_produce_type(product.name) or _infer_produce_type(product.category.name)
    image = _open_image(image_source)
    subject_pixels = _extract_subject_pixels(image)

    full_quality_result = _predict_multi_output_quality_with_keras(image)
    if full_quality_result is not None:
        return QualityInspectionResult(
            produce_type=full_quality_result.produce_type,
            freshness_label=full_quality_result.freshness_label,
            freshness_confidence=full_quality_result.freshness_confidence,
            color_score=full_quality_result.color_score,
            size_score=full_quality_result.size_score,
            ripeness_score=full_quality_result.ripeness_score,
            overall_grade=full_quality_result.overall_grade,
            suggested_action=_suggested_action(full_quality_result.overall_grade, product.stock_quantity),
            explanation=full_quality_result.explanation,
            assessed_by_model=full_quality_result.assessed_by_model,
        )

    freshness = _predict_freshness_with_keras(image, produce_type_hint)
    if freshness is None:
        fallback_confidence = 82.0 if _score_color(subject_pixels) >= 65 else 58.0
        fallback_label = "fresh" if fallback_confidence >= 65 else "rotten"
        freshness = FreshnessResult(
            produce_type=produce_type_hint,
            freshness_label=fallback_label,
            confidence=fallback_confidence,
            model_name="heuristic_quality_pipeline",
        )

    produce_type = freshness.produce_type or produce_type_hint or "unknown"
    color_score = _score_color(subject_pixels)
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
