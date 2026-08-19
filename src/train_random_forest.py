"""
Random Forest - Severity Classification
=========================================
The final decision layer. Combines:
  - Raw sensor readings
  - Isolation Forest anomaly score (how anomalous is THIS moment)
  - LSTM 24hr/48hr leak probabilities (how worried about the near future)
  - Anomaly duration (how long has this anomaly been persisting)
into a single severity grade: Low / Medium / High / Critical.

Mapping from our synthetic labels:
  none       -> Low       (healthy operation)
  warning    -> Medium
  predictive -> High
  critical   -> Critical
"""

import numpy as np
import pandas as pd
import tensorflow as tf
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, confusion_matrix
import joblib
import os

IF_SCORED_DATA_PATH = "data/r32_with_if_scores.csv"
LSTM_MODEL_PATH = "models/lstm_leak_forecast.h5"
LSTM_SCALER_PATH = "models/lstm_scaler.pkl"
MODEL_OUT = "models/random_forest_severity.pkl"
FEATURED_DATA_OUT = "data/r32_full_features.csv"

SENSOR_COLS = [
    "gas_ppm", "pressure", "temperature", "humidity", "compressor_current",
    "gas_ppm_rate_of_change", "pressure_rate_of_change", "compressor_current_rate_of_change",
    "rolling_mean_5min", "rolling_std_5min",
]

WINDOW_SIZE = 36  # must match train_lstm.py

SEVERITY_MAP = {
    "none": "Low",
    "warning": "Medium",
    "predictive": "High",
    "critical": "Critical",
}


def add_anomaly_duration(df):
    """
    For each sequence, counts how many CONSECUTIVE rows the anomaly_flag
    has been 1, resetting to 0 whenever a healthy row appears. This gives
    the model a sense of "how long has this been going on" - a leak that's
    been anomalous for 20 minutes is more urgent than one anomalous for 20 seconds.
    """
    df = df.copy()
    df["anomaly_duration"] = 0

    durations = []
    for seq_id, group in df.groupby("sequence_id"):
        flags = group["anomaly_flag"].values
        dur = np.zeros(len(flags), dtype=int)
        running = 0
        for i, f in enumerate(flags):
            running = running + 1 if f == 1 else 0
            dur[i] = running
        durations.append(pd.Series(dur, index=group.index))

    df["anomaly_duration"] = pd.concat(durations).sort_index()
    return df


def add_lstm_predictions(df):
    """
    For every row, runs the trained LSTM on the WINDOW_SIZE readings ending
    at that row (per sequence) to get leak_prob_24hr / leak_prob_48hr.
    Rows with fewer than WINDOW_SIZE prior readings in their sequence get 0.0
    (not enough history yet - matches real deployment: a freshly-installed
    sensor node can't forecast until it has accumulated enough data).
    """
    print("Loading LSTM model for feature generation...")
    model = tf.keras.models.load_model(LSTM_MODEL_PATH)
    scaler = joblib.load(LSTM_SCALER_PATH)

    df = df.copy()
    df["lstm_prob_24hr"] = 0.0
    df["lstm_prob_48hr"] = 0.0

    scaled_features = scaler.transform(df[SENSOR_COLS])
    scaled_df = pd.DataFrame(scaled_features, columns=SENSOR_COLS, index=df.index)

    for seq_id, group in df.groupby("sequence_id"):
        idx = group.index
        if len(idx) <= WINDOW_SIZE:
            continue

        seq_scaled = scaled_df.loc[idx].values
        windows = []
        window_end_positions = []
        for end in range(WINDOW_SIZE, len(idx)):
            start = end - WINDOW_SIZE
            windows.append(seq_scaled[start:end])
            window_end_positions.append(end)

        if not windows:
            continue

        X = np.array(windows)
        preds_24, preds_48 = model.predict(X, verbose=0)

        for pos, p24, p48 in zip(window_end_positions, preds_24.flatten(), preds_48.flatten()):
            row_idx = idx[pos]
            df.at[row_idx, "lstm_prob_24hr"] = p24
            df.at[row_idx, "lstm_prob_48hr"] = p48

    return df


def build_feature_dataset():
    df = pd.read_csv(IF_SCORED_DATA_PATH)

    print("Adding anomaly duration feature...")
    df = add_anomaly_duration(df)

    print("Generating LSTM-based features (this takes a few minutes)...")
    df = add_lstm_predictions(df)

    df["severity_label"] = df["severity"].map(SEVERITY_MAP)

    df.to_csv(FEATURED_DATA_OUT, index=False)
    print(f"Full feature dataset saved to {FEATURED_DATA_OUT}")
    return df


def train_random_forest(df):
    feature_cols = SENSOR_COLS + [
        "anomaly_score", "anomaly_flag", "anomaly_duration",
        "lstm_prob_24hr", "lstm_prob_48hr",
    ]

    X = df[feature_cols]
    y = df["severity_label"]

    # Stratify by sequence to avoid leakage between adjacent rows (same
    # reasoning as the LSTM fix - rows within a sequence are correlated)
    seq_ids = df["sequence_id"].unique()
    train_ids, test_ids = train_test_split(seq_ids, test_size=0.2, random_state=42)

    train_mask = df["sequence_id"].isin(train_ids)
    test_mask = df["sequence_id"].isin(test_ids)

    X_train, y_train = X[train_mask], y[train_mask]
    X_test, y_test = X[test_mask], y[test_mask]

    print(f"\nTrain: {len(X_train)} rows | Test: {len(X_test)} rows")
    print(f"Class distribution (train):\n{y_train.value_counts()}")

    model = RandomForestClassifier(
        n_estimators=200,
        max_depth=12,
        class_weight="balanced",  # severity classes are imbalanced (Low >> Critical)
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    print("\n--- Test Set Evaluation ---")
    print(classification_report(y_test, y_pred))
    print("Confusion matrix (rows=actual, cols=predicted):")
    labels = ["Low", "Medium", "High", "Critical"]
    cm = confusion_matrix(y_test, y_pred, labels=labels)
    print(pd.DataFrame(cm, index=labels, columns=labels))

    # Feature importance - genuinely useful for your report/viva
    importances = pd.Series(model.feature_importances_, index=feature_cols).sort_values(ascending=False)
    print("\nFeature importances:")
    print(importances)

    return model


if __name__ == "__main__":
    if os.path.exists(FEATURED_DATA_OUT):
        print(f"Found existing {FEATURED_DATA_OUT}, loading it directly.")
        print("(Delete this file if you want to regenerate LSTM features from scratch.)")
        df = pd.read_csv(FEATURED_DATA_OUT)
    else:
        df = build_feature_dataset()

    model = train_random_forest(df)

    os.makedirs("models", exist_ok=True)
    joblib.dump(model, MODEL_OUT)
    print(f"\nModel saved to {MODEL_OUT}")