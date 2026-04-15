from __future__ import annotations

import argparse
import colorsys
import csv
import math
from pathlib import Path

from PIL import Image, ImageStat


SUPPORTED_PRODUCE = ("apple", "banana", "orange", "tomato", "carrot", "cucumber")


def background_reference(image: Image.Image) -> tuple[int, int, int]:
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


def extract_subject_pixels(image: Image.Image) -> list[tuple[int, int, int]]:
    background = background_reference(image)
    pixels = list(image.getdata())
    subject = []
    for pixel in pixels:
        distance = math.sqrt(sum((pixel[idx] - background[idx]) ** 2 for idx in range(3)))
        if distance > 42:
            subject.append(pixel)
    return subject if subject else pixels


def clamp(score: float) -> int:
    return max(0, min(100, int(round(score))))


def score_color(subject_pixels: list[tuple[int, int, int]]) -> int:
    hsv_values = [colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0) for r, g, b in subject_pixels]
    avg_saturation = sum(hsv[1] for hsv in hsv_values) / len(hsv_values)
    avg_brightness = sum(hsv[2] for hsv in hsv_values) / len(hsv_values)
    hue_values = [hsv[0] for hsv in hsv_values]
    hue_spread = max(hue_values) - min(hue_values) if hue_values else 0.0
    uniformity = max(0.0, 1.0 - min(1.0, hue_spread * 1.8))
    return clamp((avg_saturation * 42.0) + (avg_brightness * 33.0) + (uniformity * 25.0))


def score_size(image: Image.Image, subject_pixels: list[tuple[int, int, int]]) -> int:
    subject_ratio = len(subject_pixels) / max(1, image.size[0] * image.size[1])
    ideal_ratio = 0.42
    deviation = abs(subject_ratio - ideal_ratio)
    return clamp(100.0 - min(100.0, (deviation / ideal_ratio) * 100.0))


def score_ripeness(subject_pixels: list[tuple[int, int, int]], freshness_label: str) -> int:
    hsv_values = [colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0) for r, g, b in subject_pixels]
    avg_saturation = sum(hsv[1] for hsv in hsv_values) / len(hsv_values)
    avg_brightness = sum(hsv[2] for hsv in hsv_values) / len(hsv_values)
    freshness_seed = 85.0 if freshness_label == "fresh" else 45.0
    return clamp((freshness_seed * 0.55) + (avg_saturation * 100.0 * 0.25) + (avg_brightness * 100.0 * 0.2))


def grade_from_scores(color_score: int, size_score: int, ripeness_score: int) -> str:
    if color_score < 65 or size_score < 70 or ripeness_score < 60:
        return "C"
    if color_score < 75 or size_score < 80 or ripeness_score < 70:
        return "B"
    return "A"


def infer_labels_from_parent(path: Path) -> tuple[str, str]:
    folder = path.parent.name.lower()
    freshness = "fresh" if "fresh" in folder or "healthy" in folder else "rotten"
    produce = next((name for name in SUPPORTED_PRODUCE if name in folder), "")
    if not produce:
        file_path = str(path).lower()
        produce = next((name for name in SUPPORTED_PRODUCE if name in file_path), "unknown")
    return produce, freshness


def collect_images(dataset_root: Path) -> list[Path]:
    extensions = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    return [path for path in dataset_root.rglob("*") if path.suffix.lower() in extensions]


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap quality labels CSV from fresh/rotten image folders.")
    parser.add_argument("--dataset-root", required=True, help="Path to dataset root.")
    parser.add_argument("--output-csv", required=True, help="Path to output CSV.")
    args = parser.parse_args()

    dataset_root = Path(args.dataset_root).resolve()
    output_csv = Path(args.output_csv).resolve()
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    for image_path in collect_images(dataset_root):
        produce_type, freshness_label = infer_labels_from_parent(image_path)
        image = Image.open(image_path).convert("RGB")
        subject_pixels = extract_subject_pixels(image)
        color_score = score_color(subject_pixels)
        size_score = score_size(image, subject_pixels)
        ripeness_score = score_ripeness(subject_pixels, freshness_label)
        grade = grade_from_scores(color_score, size_score, ripeness_score)
        rows.append(
            {
                "image_path": str(image_path),
                "produce_type": produce_type,
                "freshness_label": freshness_label,
                "color_score": color_score,
                "size_score": size_score,
                "ripeness_score": ripeness_score,
                "grade": grade,
            }
        )

    with output_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["image_path", "produce_type", "freshness_label", "color_score", "size_score", "ripeness_score", "grade"],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
