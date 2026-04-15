from __future__ import annotations

from pathlib import Path
import json
import sys


def main() -> int:
    print(f"Python: {sys.version}")
    try:
        import tensorflow as tf
        import numpy as np  # noqa: F401
    except Exception as exc:
        print(f"TensorFlow runtime unavailable: {exc}")
        return 1

    repo_root = Path(__file__).resolve().parents[1]
    model_path = repo_root / "weights" / "fruit_vegetable_classifier.h5"
    labels_path = repo_root / "weights" / "fruit_vegetable_classifier_labels.json"
    print(f"TensorFlow: {tf.__version__}")
    print(f"Model exists: {model_path.exists()} -> {model_path}")
    print(f"Labels exist: {labels_path.exists()} -> {labels_path}")
    if not model_path.exists():
        return 1

    model = tf.keras.models.load_model(model_path)
    print("Loaded model successfully.")
    print(f"Input shape: {model.input_shape}")
    print(f"Output shape: {model.output_shape}")
    if labels_path.exists():
        labels = json.loads(labels_path.read_text(encoding="utf-8"))
        if isinstance(labels, dict):
            print(f"Classifier metadata keys: {sorted(labels.keys())}")

    multi_model_path = repo_root / "weights" / "quality_multi_output_model.keras"
    metadata_path = repo_root / "weights" / "quality_multi_output_metadata.json"
    print(f"Multi-output model exists: {multi_model_path.exists()} -> {multi_model_path}")
    print(f"Multi-output metadata exists: {metadata_path.exists()} -> {metadata_path}")
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        print(f"Metadata keys: {sorted(metadata.keys())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
