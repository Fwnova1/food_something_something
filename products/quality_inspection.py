from __future__ import annotations

import base64
import json
import mimetypes
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from django.conf import settings


@dataclass
class QualityInspectionResult:
    freshness_label: str
    freshness_confidence: float
    size_grade: str
    color_grade: str
    overall_grade: str
    assessed_by_model: str
    explanation: str
    gradcam_image_url: str = ""


def _build_multipart_form_data(image_bytes: bytes, filename: str, content_type: str, produce_hint: str) -> tuple[bytes, str]:
    boundary = f"----food-quality-{uuid4().hex}"
    lines = []
    lines.append(f"--{boundary}\r\n".encode("utf-8"))
    lines.append(b'Content-Disposition: form-data; name="file"; filename="' + filename.encode("utf-8") + b'"\r\n')
    lines.append(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
    lines.append(image_bytes)
    lines.append(b"\r\n")
    lines.append(f"--{boundary}\r\n".encode("utf-8"))
    lines.append(b'Content-Disposition: form-data; name="produce_type_hint"\r\n\r\n')
    lines.append((produce_hint or "").encode("utf-8"))
    lines.append(b"\r\n")
    lines.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(lines), boundary


def _save_gradcam_from_base64(gradcam_base64: str) -> str:
    media_root = Path(settings.MEDIA_ROOT) / "quality_inspections" / "gradcam"
    media_root.mkdir(parents=True, exist_ok=True)
    output_path = media_root / f"gradcam_{uuid4().hex}.jpg"
    output_path.write_bytes(base64.b64decode(gradcam_base64))
    return f"{settings.MEDIA_URL}quality_inspections/gradcam/{output_path.name}"


def _save_gradcam_from_data_uri(data_uri: str) -> str:
    if not data_uri.startswith("data:image"):
        return ""
    marker = ";base64,"
    if marker not in data_uri:
        return ""
    payload = data_uri.split(marker, 1)[1].strip()
    if not payload:
        return ""
    return _save_gradcam_from_base64(payload)


def _call_remote_quality_api(image_source, produce_hint: str) -> dict:
    endpoint = (getattr(settings, "QUALITY_MODEL_API_URL", "") or "").strip()
    if not endpoint:
        raise RuntimeError("QUALITY_MODEL_API_URL is not configured.")

    timeout_seconds = int(getattr(settings, "QUALITY_MODEL_API_TIMEOUT_SECONDS", 45))
    api_key = (getattr(settings, "QUALITY_MODEL_API_KEY", "") or "").strip()
    auth_header_name = (getattr(settings, "QUALITY_MODEL_AUTH_HEADER", "X-API-Key") or "X-API-Key").strip()

    if hasattr(image_source, "open"):
        image_source.open("rb")
    image_bytes = image_source.read()
    if hasattr(image_source, "seek"):
        image_source.seek(0)

    filename = Path(getattr(image_source, "name", "inspection.jpg")).name
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    body, boundary = _build_multipart_form_data(image_bytes, filename, content_type, produce_hint)

    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Accept": "application/json",
    }
    if api_key:
        headers[auth_header_name] = api_key

    request = urllib.request.Request(endpoint, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = response.read().decode("utf-8")
            parsed = json.loads(payload) if payload else {}
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Quality API HTTP {exc.code}: {error_body[:300]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Quality API is unreachable: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("Quality API returned invalid JSON.") from exc

    if not isinstance(parsed, dict):
        raise RuntimeError("Quality API response must be a JSON object.")
    return parsed


def _safe_percent(value, default: float = 0.0) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = float(default)
    return max(0.0, min(100.0, score))


def _grade_from_score(score: float) -> str:
    if score >= 80.0:
        return "A"
    if score >= 60.0:
        return "B"
    return "C"


def _extract_feature_grade(payload: dict, score_keys: tuple[str, ...], label_keys: tuple[str, ...], fallback_score: float) -> tuple[str, float]:
    for key in score_keys:
        if key in payload:
            score = _safe_percent(payload.get(key), default=fallback_score)
            return _grade_from_score(score), score

    label_to_score = {
        "a": 90.0,
        "excellent": 90.0,
        "large": 90.0,
        "good": 75.0,
        "b": 75.0,
        "medium": 75.0,
        "fair": 60.0,
        "small": 60.0,
        "c": 45.0,
        "poor": 45.0,
        "bad": 45.0,
    }
    for key in label_keys:
        raw = payload.get(key)
        if isinstance(raw, str):
            mapped = label_to_score.get(raw.strip().lower())
            if mapped is not None:
                return _grade_from_score(mapped), mapped

    score = _safe_percent(fallback_score, default=fallback_score)
    return _grade_from_score(score), score


def _compute_overall_grade(freshness_label: str, freshness_confidence: float, size_score: float, color_score: float) -> str:
    if freshness_label.strip().lower() == "rotten":
        return "C"

    freshness_quality_score = freshness_confidence
    blended = (freshness_quality_score * 0.5) + (size_score * 0.25) + (color_score * 0.25)
    return _grade_from_score(blended)


def inspect_product_quality(image_source, produce_hint: str = "") -> QualityInspectionResult:
    payload = _call_remote_quality_api(image_source, produce_hint=produce_hint)

    gradcam_image_url = (payload.get("gradcam_image_url") or "").strip()
    gradcam_data_uri = (payload.get("gradcam") or "").strip()
    gradcam_base64 = payload.get("gradcam_base64")
    if not gradcam_image_url and gradcam_data_uri:
        try:
            gradcam_image_url = _save_gradcam_from_data_uri(gradcam_data_uri)
        except Exception:
            gradcam_image_url = ""
    if not gradcam_image_url and isinstance(gradcam_base64, str) and gradcam_base64.strip():
        try:
            gradcam_image_url = _save_gradcam_from_base64(gradcam_base64.strip())
        except Exception:
            gradcam_image_url = ""

    raw_label = (payload.get("label") or "").strip()
    freshness_label = (payload.get("freshness_label") or raw_label or "unknown").strip()
    confidence = _safe_percent(
        payload.get("freshness_confidence", payload.get("confidence_percent", payload.get("confidence", 0.0))) or 0.0
    )

    size_grade, size_score = _extract_feature_grade(
        payload,
        score_keys=("size_score", "fruit_size_score", "size_percent"),
        label_keys=("size_grade", "size_label", "fruit_size_label"),
        fallback_score=confidence,
    )
    color_grade, color_score = _extract_feature_grade(
        payload,
        score_keys=("color_score", "fruit_color_score", "color_percent"),
        label_keys=("color_grade", "color_label", "fruit_color_label"),
        fallback_score=confidence,
    )
    overall_grade = _compute_overall_grade(freshness_label, confidence, size_score, color_score)

    return QualityInspectionResult(
        freshness_label=freshness_label,
        freshness_confidence=round(confidence, 2),
        size_grade=size_grade,
        color_grade=color_grade,
        overall_grade=overall_grade,
        assessed_by_model=(payload.get("assessed_by_model") or payload.get("model_name") or "remote_quality_model_api").strip(),
        explanation=(payload.get("explanation") or "Result generated by remote quality model API.").strip(),
        gradcam_image_url=gradcam_image_url,
    )
