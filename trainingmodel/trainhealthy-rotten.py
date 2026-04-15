import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
import json
import tensorflow as tf
from tensorflow.keras.preprocessing.image import ImageDataGenerator
from tensorflow.keras.applications.efficientnet import preprocess_input

gpus = tf.config.list_physical_devices('GPU')
if gpus:
    try:
        for gpu in gpus:
            tf.config.experimental.set_memory_growth(gpu, True)
        print(f'GPUs available: {len(gpus)}')
    except RuntimeError as e:
        print(e)
else:
    print('No GPU found, using CPU')

IMG_SIZE = 224
BATCH_SIZE = 32
EPOCHS = 1

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATA_PATH = PROJECT_ROOT / "data" / "Fruit And Vegetable Diseases Dataset"
WEIGHTS_DIR = PROJECT_ROOT / "weights"
MODEL_OUTPUT_PATH = WEIGHTS_DIR / "fruit_vegetable_classifier.h5"
LABELS_OUTPUT_PATH = WEIGHTS_DIR / "fruit_vegetable_classifier_labels.json"
print(f"Dataset path: {DATA_PATH.exists()}")

def get_folder_stats(data_path):
    folders = list(data_path.iterdir())
    stats = {}
    total = 0
    image_suffixes = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    for folder in folders:
        if folder.is_dir():
            count = sum(1 for file in folder.iterdir() if file.is_file() and file.suffix.lower() in image_suffixes)
            stats[folder.name] = count
            total += count
    return stats, total

stats, total_images = get_folder_stats(DATA_PATH)
print(f"Total images: {total_images}")
print(f"Classes: {len(stats)}")
for name, count in stats.items():
    print(f"  {name}: {count}")

train_datagen = ImageDataGenerator(
    preprocessing_function=preprocess_input,
    validation_split=0.2,
    rotation_range=20,
    width_shift_range=0.2,
    height_shift_range=0.2,
    horizontal_flip=True
)

val_datagen = ImageDataGenerator(
    preprocessing_function=preprocess_input,
    validation_split=0.2
)

preview_datagen = ImageDataGenerator(validation_split=0.2)

train_generator = train_datagen.flow_from_directory(
    DATA_PATH,
    target_size=(IMG_SIZE, IMG_SIZE),
    batch_size=BATCH_SIZE,
    class_mode='categorical',
    subset='training',
    seed=42
)

val_generator = val_datagen.flow_from_directory(
    DATA_PATH,
    target_size=(IMG_SIZE, IMG_SIZE),
    batch_size=BATCH_SIZE,
    class_mode='categorical',
    subset='validation',
    seed=42,
    shuffle=False
)

print(f"\nClasses: {train_generator.class_indices}")
print(f"Training samples: {train_generator.samples}")
print(f"Validation samples: {val_generator.samples}")

NUM_CLASSES = train_generator.num_classes
print(f"Detected classes: {NUM_CLASSES}")
WEIGHTS_DIR.mkdir(parents=True, exist_ok=True)
ordered_labels = [label for label, _ in sorted(train_generator.class_indices.items(), key=lambda item: item[1])]
LABELS_OUTPUT_PATH.write_text(
    json.dumps(
        {
            "class_indices": train_generator.class_indices,
            "labels": ordered_labels,
            "image_size": IMG_SIZE,
        },
        indent=2,
    ),
    encoding="utf-8",
)
print(f"Saved labels to {LABELS_OUTPUT_PATH}")

preview_generator = preview_datagen.flow_from_directory(
    DATA_PATH,
    target_size=(IMG_SIZE, IMG_SIZE),
    batch_size=8,
    class_mode='categorical',
    subset='training',
    seed=42,
    shuffle=True
)

fig, axes = plt.subplots(2, 4, figsize=(12, 6))
axes = axes.flatten()

preview_images, preview_labels = next(preview_generator)
for i in range(8):
    axes[i].imshow(preview_images[i].astype("uint8"))
    class_name = list(preview_generator.class_indices.keys())[np.argmax(preview_labels[i])]
    axes[i].set_title(class_name[:20], fontsize=8)
    axes[i].axis('off')

plt.tight_layout()
plt.show()

from tensorflow.keras.applications import EfficientNetB0
from tensorflow.keras.layers import Dense, GlobalAveragePooling2D, Dropout
from tensorflow.keras.models import Model
from tensorflow.keras.optimizers import Adam
from tensorflow.keras.callbacks import EarlyStopping, ReduceLROnPlateau

base_model = EfficientNetB0(weights='imagenet', include_top=False, input_shape=(IMG_SIZE, IMG_SIZE, 3))
base_model.trainable = False

x = base_model.output
x = GlobalAveragePooling2D()(x)
x = Dense(128, activation='relu')(x)
x = Dropout(0.5)(x)
predictions = Dense(NUM_CLASSES, activation='softmax')(x)

model = Model(inputs=base_model.input, outputs=predictions)

model.compile(
    optimizer=Adam(learning_rate=0.001),
    loss='categorical_crossentropy',
    metrics=['accuracy']
)

callbacks = [
    EarlyStopping(monitor='val_loss', patience=3, restore_best_weights=True),
    ReduceLROnPlateau(monitor='val_loss', factor=0.2, patience=2, min_lr=1e-6)
]

history = model.fit(
    train_generator,
    epochs=EPOCHS,
    validation_data=val_generator,
    callbacks=callbacks
)

fig, axes = plt.subplots(1, 2, figsize=(12, 4))

axes[0].plot(history.history['accuracy'], label='Training')
axes[0].plot(history.history['val_accuracy'], label='Validation')
axes[0].set_title('Model Accuracy')
axes[0].set_xlabel('Epoch')
axes[0].set_ylabel('Accuracy')
axes[0].legend()

axes[1].plot(history.history['loss'], label='Training')
axes[1].plot(history.history['val_loss'], label='Validation')
axes[1].set_title('Model Loss')
axes[1].set_xlabel('Epoch')
axes[1].set_ylabel('Loss')
axes[1].legend()

plt.tight_layout()
plt.show()

base_model.trainable = True
for layer in base_model.layers[:80]:
    layer.trainable = False

model.compile(
    optimizer=Adam(learning_rate=0.0001),
    loss='categorical_crossentropy',
    metrics=['accuracy']
)

history_finetune = model.fit(
    train_generator,
    epochs=1,
    validation_data=val_generator,
    callbacks=callbacks
)

eval_result = model.evaluate(val_generator)
print(f"\nValidation Loss: {eval_result[0]:.4f}")
print(f"Validation Accuracy: {eval_result[1]:.4f}")

model.save(MODEL_OUTPUT_PATH)
print(f"Model saved to {MODEL_OUTPUT_PATH}")
