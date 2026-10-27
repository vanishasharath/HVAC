"""
Isolation Forest - Real-Time Anomaly Detection
================================================
Trains ONLY on healthy operational data (unsupervised).
Learns what "normal" R-32 unit behavior looks like, flags anything
that deviates as anomalous - without ever seeing a labeled leak.
"""

import pandas as pd
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.model_selection import train_test_split
import joblib
import os

DATA_PATH = "data/r32_healthy_only.csv"
FULL_DATA_PATH = "data/r32_synthetic_full.csv"  # used only for evaluation, not training
MODEL_OUT = "models/isolation_forest_r32.pkl"

# The feature set the model actually trains on.
# NOTE: we exclude label/severity/sequence_id - those are metadata, not sensor features.
FEATURE_COLS = [
    "gas_ppm", "pressure", "temperature", "humidity", "compressor_current",
    "gas_ppm_rate_of_change", "pressure_rate_of_change", "compressor_current_rate_of_change",
    "rolling_mean_5min", "rolling_std_5min",
]


def load_healthy_data():
    df = pd.read_csv(DATA_PATH)
    return df


def train_isolation_forest(df, contamination=0.02):
    """
    contamination: expected proportion of outliers in TRAINING data.
    Kept low (0.01-0.03) per your notes - gas leaks are rare events,
    and training data is meant to be ~100% healthy. This just gives
    the model a little tolerance for sensor noise/edge cases.
    """
    X = df[FEATURE_COLS]

    X_train, X_val = train_test_split(X, test_size=0.15, random_state=42)

    model = IsolationForest(
        n_estimators=150,       # number of trees - more trees = more stable anomaly scores
        max_samples="auto",
        contamination=contamination,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_train)

    # Sanity check: on held-out healthy data, most predictions should be "normal" (1)
    val_preds = model.predict(X_val)   # returns 1 (normal) or -1 (anomaly)
    false_positive_rate = (val_preds == -1).mean()
    print(f"Trained on {len(X_train)} healthy samples.")
    print(f"Held-out healthy validation set: {false_positive_rate*100:.2f}% flagged as anomalous "
          f"(this is your false-positive rate - lower is better, should roughly track contamination).")

    return model


def evaluate_on_leak_data(model):
    """
    This is the real test: does the model correctly flag leak rows as anomalous,
    even though it never saw a single leak sample during training?
    """
    df = pd.read_csv(FULL_DATA_PATH)
    X = df[FEATURE_COLS]
    y_true = df["label"]  # 0 = healthy, 1 = leak (ground truth, for evaluation only)

    preds = model.predict(X)
    y_pred = (preds == -1).astype(int)  # convert -1/1 -> 1/0 anomaly flag

    scores = -model.decision_function(X)  # higher score = more anomalous (flip sign for intuitive direction)
    df["anomaly_score"] = scores
    df["anomaly_flag"] = y_pred

    from sklearn.metrics import classification_report, confusion_matrix
    print("\n--- Evaluation against FULL dataset (including leak rows) ---")
    print("Note: Isolation Forest was NEVER trained on leak data - this measures")
    print("whether the anomaly pattern alone is enough to catch leaks.\n")
    print(classification_report(y_true, y_pred, target_names=["healthy", "leak"]))
    print("Confusion matrix:")
    print(confusion_matrix(y_true, y_pred))

    return df


def save_model(model):
    os.makedirs("models", exist_ok=True)
    joblib.dump(model, MODEL_OUT)
    print(f"\nModel saved to {MODEL_OUT}")


if __name__ == "__main__":
    healthy_df = load_healthy_data()
    model = train_isolation_forest(healthy_df, contamination=0.02)
    evaluated_df = evaluate_on_leak_data(model)
    save_model(model)

    # Save scored dataset too - useful later for training Random Forest
    # (it needs isolation_forest_anomaly_score as an input feature)
    evaluated_df.to_csv("data/r32_with_if_scores.csv", index=False)
    print("Scored dataset saved to data/r32_with_if_scores.csv")