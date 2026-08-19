"""
LSTM - 24/48 Hour Leak Probability Forecasting
================================================
Looks at a sliding window of recent sensor readings and forecasts the
probability of a leak occurring within the next 24hrs AND next 48hrs.

Uses sigmoid (not softmax) outputs because the two windows are NOT
mutually exclusive - a unit can be likely to leak in both.

NOTE ON SYNTHETIC DATA LIMITATION:
Our synthetic sequences are short (60-300 min) since they're built for
Isolation Forest / Random Forest row-level training. True 24-48hr forecasting
needs multi-day sequences. This script builds the LSTM pipeline correctly and
trains it on what we have (relabeled as "will this window progress into a
leak within its own remaining horizon") - you MUST regenerate longer synthetic
sequences (multi-day) before your final report numbers.
"""

import numpy as np
import pandas as pd
import tensorflow as tf
from tensorflow.keras import layers, models
from sklearn.preprocessing import MinMaxScaler
from sklearn.model_selection import train_test_split
import joblib
import os

FULL_DATA_PATH = "data/r32_synthetic_full.csv"
MODEL_OUT = "models/lstm_leak_forecast.h5"
SCALER_OUT = "models/lstm_scaler.pkl"

FEATURE_COLS = [
    "gas_ppm", "pressure", "temperature", "humidity", "compressor_current",
    "gas_ppm_rate_of_change", "pressure_rate_of_change", "compressor_current_rate_of_change",
    "rolling_mean_5min", "rolling_std_5min",
]

WINDOW_SIZE = 36   # 36 samples = 6 minutes at 10s interval (small window, see note below)
# NOTE: For a real 6-hour window at 10s sampling you'd use WINDOW_SIZE=2160.
# We use a smaller window here so training works with our current short synthetic
# sequences. Once you generate longer sequences, bump this up and re-train -
# the code doesn't change, just the data and this constant.


def build_windows(df, sequence_ids=None):
    """
    Slides a window across each sequence_id independently (never crosses
    sequence boundaries) and builds:
      X: (n_windows, WINDOW_SIZE, n_features)
      y_24hr: probability label for near-term leak (proxy, see note)
      y_48hr: probability label for longer-term leak (proxy, see note)

    sequence_ids: if provided, only builds windows from these sequences
    (used to keep train/val split at the SEQUENCE level, not window level -
    see note in train() about why this matters).

    STRIDE: windows are built every STRIDE samples, not every single sample.
    Consecutive windows (stride=1) are ~97% identical and cause massive
    data leakage between train/val if split randomly - STRIDE thins them out.
    """
    STRIDE = 6  # only start a new window every 6 samples (~1 min apart)
    X, y24, y48 = [], [], []

    groups = df.groupby("sequence_id")
    for seq_id, group in groups:
        if sequence_ids is not None and seq_id not in sequence_ids:
            continue

        group = group.reset_index(drop=True)
        features = group[FEATURE_COLS].values
        labels = group["label"].values

        if len(group) <= WINDOW_SIZE:
            continue

        for start in range(0, len(group) - WINDOW_SIZE, STRIDE):
            end = start + WINDOW_SIZE
            window = features[start:end]

            near_end = min(end + 30, len(group))
            far_end = min(end + 90, len(group))

            near_leak = 1 if labels[end:near_end].sum() > 0 else 0
            far_leak = 1 if labels[end:far_end].sum() > 0 else 0

            X.append(window)
            y24.append(near_leak)
            y48.append(far_leak)

    return np.array(X), np.array(y24), np.array(y48)


def build_lstm_model(n_features):
    inputs = layers.Input(shape=(WINDOW_SIZE, n_features))
    x = layers.LSTM(64, return_sequences=True, dropout=0.2)(inputs)
    x = layers.LSTM(64, dropout=0.2)(x)
    x = layers.Dense(32, activation="relu")(x)
    x = layers.Dropout(0.2)(x)

    out_24hr = layers.Dense(1, activation="sigmoid", name="leak_prob_24hr")(x)
    out_48hr = layers.Dense(1, activation="sigmoid", name="leak_prob_48hr")(x)

    model = models.Model(inputs=inputs, outputs=[out_24hr, out_48hr])
    model.compile(
        optimizer="adam",
        loss={"leak_prob_24hr": "binary_crossentropy", "leak_prob_48hr": "binary_crossentropy"},
        metrics={"leak_prob_24hr": ["accuracy"], "leak_prob_48hr": ["accuracy"]},
    )
    return model


def train():
    df = pd.read_csv(FULL_DATA_PATH)

    scaler = MinMaxScaler()
    df[FEATURE_COLS] = scaler.fit_transform(df[FEATURE_COLS])

    all_seq_ids = df["sequence_id"].unique()
    train_seq_ids, val_seq_ids = train_test_split(all_seq_ids, test_size=0.2, random_state=42)

    print("Building sliding windows...")
    X_train, y24_train, y48_train = build_windows(df, sequence_ids=set(train_seq_ids))
    X_val, y24_val, y48_val = build_windows(df, sequence_ids=set(val_seq_ids))
    print(f"Train: {len(X_train)} windows from {len(train_seq_ids)} sequences")
    print(f"Val:   {len(X_val)} windows from {len(val_seq_ids)} sequences")
    print(f"24hr-proxy positive rate (train): {y24_train.mean()*100:.1f}%")
    print(f"48hr-proxy positive rate (train): {y48_train.mean()*100:.1f}%")

    model = build_lstm_model(n_features=X_train.shape[2])
    model.summary()

    callbacks = [
        tf.keras.callbacks.EarlyStopping(
            monitor="val_loss", patience=3, restore_best_weights=True
        ),
        tf.keras.callbacks.ReduceLROnPlateau(
            monitor="val_loss", factor=0.5, patience=2, min_lr=1e-5
        ),
    ]

    history = model.fit(
        X_train,
        {"leak_prob_24hr": y24_train, "leak_prob_48hr": y48_train},
        validation_data=(X_val, {"leak_prob_24hr": y24_val, "leak_prob_48hr": y48_val}),
        epochs=15,
        batch_size=64,
        callbacks=callbacks,
        verbose=2,
    )

    os.makedirs("models", exist_ok=True)
    model.save(MODEL_OUT)
    joblib.dump(scaler, SCALER_OUT)
    print(f"\nModel saved to {MODEL_OUT}")
    print(f"Scaler saved to {SCALER_OUT}")

    return model, history


if __name__ == "__main__":
    train()
