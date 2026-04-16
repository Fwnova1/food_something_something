from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
import tensorflow as tf
from sklearn.model_selection import train_test_split


AUTOTUNE = tf.data.AUTOTUNE


def parse_args():
    parser = argparse.ArgumentParser(description="Train multi-output CNN for product quality inspection.")
    parser.add_argument("--labels-csv", required=True, help="CSV with image_path, produce_type, freshness_label, color_score, size_score, ripeness_score, grade")
    parser.add_argument("--output-model", required=True, help="Path to output .keras model")
    parser.add_argument("--output-metadata", required=True, help="Path to output metadata JSON")
    parser.add_argument("--image-size", type=int, default=224)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--epochs", type=int, default=15)
    parser.add_argument("--val-size", type=float, default=0.2)
    return parser.parse_args()


def load_and_preprocess_image(path: tf.Tensor, image_size: int):
    image_bytes = tf.io.read_file(path)
    image = tf.image.decode_image(image_bytes, channels=3, expand_animations=False)
    image = tf.image.resize(image, [image_size, image_size])
    image = tf.cast(image, tf.float32) / 255.0
    return image


def build_dataset(frame: pd.DataFrame, image_size: int, batch_size: int, produce_lookup: dict, freshness_lookup: dict, grade_lookup: dict, training: bool):
    image_paths = frame["image_path"].astype(str).tolist()
    produce_ids = frame["produce_type"].map(produce_lookup).astype("int32").tolist()
    freshness_ids = frame["freshness_label"].map(freshness_lookup).astype("int32").tolist()
    color_scores = (frame["color_score"].astype("float32") / 100.0).tolist()
    size_scores = (frame["size_score"].astype("float32") / 100.0).tolist()
    ripeness_scores = (frame["ripeness_score"].astype("float32") / 100.0).tolist()
    grade_ids = frame["grade"].map(grade_lookup).astype("int32").tolist()

    dataset = tf.data.Dataset.from_tensor_slices(
        (
            image_paths,
            {
                "produce_type": produce_ids,
                "freshness": freshness_ids,
                "color_score": color_scores,
                "size_score": size_scores,
                "ripeness_score": ripeness_scores,
                "grade": grade_ids,
            },
        )
    )

    if training:
        dataset = dataset.shuffle(len(frame), reshuffle_each_iteration=True)

    def _map(path, targets):
        image = load_and_preprocess_image(path, image_size)
        return image, {
            "produce_type": tf.one_hot(targets["produce_type"], depth=len(produce_lookup)),
            "freshness": tf.one_hot(targets["freshness"], depth=len(freshness_lookup)),
            "color_score": tf.expand_dims(tf.cast(targets["color_score"], tf.float32), axis=-1),
            "size_score": tf.expand_dims(tf.cast(targets["size_score"], tf.float32), axis=-1),
            "ripeness_score": tf.expand_dims(tf.cast(targets["ripeness_score"], tf.float32), axis=-1),
            "grade": tf.one_hot(targets["grade"], depth=len(grade_lookup)),
        }

    return dataset.map(_map, num_parallel_calls=AUTOTUNE).batch(batch_size).prefetch(AUTOTUNE)


def build_model(image_size: int, produce_classes: int, freshness_classes: int, grade_classes: int):
    inputs = tf.keras.Input(shape=(image_size, image_size, 3), name="image")

    x = tf.keras.layers.Conv2D(32, 3, activation="relu", padding="same")(inputs)
    x = tf.keras.layers.MaxPooling2D()(x)
    x = tf.keras.layers.Conv2D(64, 3, activation="relu", padding="same")(x)
    x = tf.keras.layers.MaxPooling2D()(x)
    x = tf.keras.layers.Conv2D(128, 3, activation="relu", padding="same")(x)
    x = tf.keras.layers.MaxPooling2D()(x)
    x = tf.keras.layers.Conv2D(256, 3, activation="relu", padding="same")(x)
    x = tf.keras.layers.GlobalAveragePooling2D()(x)
    x = tf.keras.layers.Dropout(0.25)(x)
    shared = tf.keras.layers.Dense(256, activation="relu")(x)

    produce_head = tf.keras.layers.Dense(produce_classes, activation="softmax", name="produce_type")(shared)
    freshness_head = tf.keras.layers.Dense(freshness_classes, activation="softmax", name="freshness")(shared)
    color_head = tf.keras.layers.Dense(1, activation="sigmoid", name="color_score")(shared)
    size_head = tf.keras.layers.Dense(1, activation="sigmoid", name="size_score")(shared)
    ripeness_head = tf.keras.layers.Dense(1, activation="sigmoid", name="ripeness_score")(shared)
    grade_head = tf.keras.layers.Dense(grade_classes, activation="softmax", name="grade")(shared)

    model = tf.keras.Model(
        inputs=inputs,
        outputs={
            "produce_type": produce_head,
            "freshness": freshness_head,
            "color_score": color_head,
            "size_score": size_head,
            "ripeness_score": ripeness_head,
            "grade": grade_head,
        },
    )
    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=1e-3),
        loss={
            "produce_type": "categorical_crossentropy",
            "freshness": "categorical_crossentropy",
            "color_score": "mse",
            "size_score": "mse",
            "ripeness_score": "mse",
            "grade": "categorical_crossentropy",
        },
        metrics={
            "produce_type": ["accuracy"],
            "freshness": ["accuracy"],
            "color_score": ["mae"],
            "size_score": ["mae"],
            "ripeness_score": ["mae"],
            "grade": ["accuracy"],
        },
        loss_weights={
            "produce_type": 1.0,
            "freshness": 1.0,
            "color_score": 0.8,
            "size_score": 0.6,
            "ripeness_score": 0.8,
            "grade": 1.2,
        },
    )
    return model


def main() -> int:
    args = parse_args()
    frame = pd.read_csv(args.labels_csv)
    frame = frame.dropna(subset=["image_path", "produce_type", "freshness_label", "color_score", "size_score", "ripeness_score", "grade"]).copy()

    produce_labels = sorted(frame["produce_type"].astype(str).unique().tolist())
    freshness_labels = sorted(frame["freshness_label"].astype(str).unique().tolist())
    grade_labels = ["A", "B", "C"]

    produce_lookup = {label: idx for idx, label in enumerate(produce_labels)}
    freshness_lookup = {label: idx for idx, label in enumerate(freshness_labels)}
    grade_lookup = {label: idx for idx, label in enumerate(grade_labels)}

    train_df, val_df = train_test_split(
        frame,
        test_size=args.val_size,
        random_state=42,
        stratify=frame["grade"],
    )

    train_ds = build_dataset(train_df, args.image_size, args.batch_size, produce_lookup, freshness_lookup, grade_lookup, training=True)
    val_ds = build_dataset(val_df, args.image_size, args.batch_size, produce_lookup, freshness_lookup, grade_lookup, training=False)

    model = build_model(args.image_size, len(produce_labels), len(freshness_labels), len(grade_labels))
    callbacks = [
        tf.keras.callbacks.EarlyStopping(monitor="val_loss", patience=4, restore_best_weights=True),
        tf.keras.callbacks.ReduceLROnPlateau(monitor="val_loss", patience=2, factor=0.5),
    ]
    history = model.fit(train_ds, validation_data=val_ds, epochs=args.epochs, callbacks=callbacks)

    output_model = Path(args.output_model).resolve()
    output_metadata = Path(args.output_metadata).resolve()
    output_model.parent.mkdir(parents=True, exist_ok=True)
    output_metadata.parent.mkdir(parents=True, exist_ok=True)

    model.save(output_model)
    metadata = {
        "image_size": args.image_size,
        "produce_labels": produce_labels,
        "freshness_labels": freshness_labels,
        "grade_labels": grade_labels,
        "history_keys": list(history.history.keys()),
        "train_samples": len(train_df),
        "validation_samples": len(val_df),
    }
    output_metadata.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    print(f"Saved model to {output_model}")
    print(f"Saved metadata to {output_metadata}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
