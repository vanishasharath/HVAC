"""
LSTM evaluation on a TRUE held-out set of sequences.

What changed vs. the previous version
-------------------------------------
1. SPLIT FIX: uses the same split as train_lstm.py
   (train_test_split(all_ids, test_size=0.2, random_state=42)).
   The old script used np.random.permutation, which picked different
   sequences -> it was probably scoring sequences the model trained on.
   If models/lstm_val_sequence_ids.json exists (see the snippet to add to
   train_lstm.py at the bottom of this file) that file is used instead.
2. PRE-ONSET METRICS: windows that already contain leak samples are trivially
   positive (labels stay 1 after onset). Metrics are now reported for
   (a) all windows and (b) PRE-ONSET windows only (no leak label inside the
   window), which is the part that actually tests forecasting.
3. Scaler is called with a DataFrame (removes the feature-name warning).
4. roc_auc bug removed (it relied on locals()).
5. Optional comparison against the OLD (numpy) split, so you can see which
   split the saved model was really trained on: the set with clearly better
   scores is probably the one it trained on.
"""

import json
import os

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split

# ============================================================
# CONFIGURATION
# ============================================================

DATA_PATH = "data/r32_synthetic_full.csv"
MODEL_PATH = "models/lstm_leak_forecast.h5"
SCALER_PATH = "models/lstm_scaler.pkl"
VAL_IDS_PATH = "models/lstm_val_sequence_ids.json"  # written by train_lstm.py (optional)
OUTPUT_PATH = "data/lstm_validation_predictions.csv"

WINDOW_SIZE = 36
STRIDE = 6
NEAR_HORIZON = 30  # 30 samples x 10 s = 5 minutes
FAR_HORIZON = 90   # 90 samples x 10 s = 15 minutes
THRESHOLD = 0.5

COMPARE_OLD_SPLIT = True  # also score the sequences the OLD script used

FEATURE_COLS = [
    "gas_ppm",
    "pressure",
    "temperature",
    "humidity",
    "compressor_current",
    "gas_ppm_rate_of_change",
    "pressure_rate_of_change",
    "compressor_current_rate_of_change",
    "rolling_mean_5min",
    "rolling_std_5min",
]


# ============================================================
# SPLITS
# ============================================================

def get_validation_ids(df):
    """Same split as train_lstm.py, or the saved IDs if available."""
    if os.path.exists(VAL_IDS_PATH):
        with open(VAL_IDS_PATH) as f:
            ids = sorted(int(i) for i in json.load(f))
        return ids, f"loaded from {VAL_IDS_PATH}"

    all_ids = df["sequence_id"].unique()
    _, val_ids = train_test_split(all_ids, test_size=0.2, random_state=42)
    return sorted(int(i) for i in val_ids), "train_test_split(random_state=42), same as train_lstm.py"


def get_old_split_ids(df):
    """The split the previous evaluate_lstm.py used (for comparison only)."""
    ids = sorted(df["sequence_id"].unique())
    shuffled = np.random.RandomState(42).permutation(ids)
    cut = int(0.80 * len(shuffled))
    return sorted(int(i) for i in shuffled[cut:])


# ============================================================
# WINDOWS
# ============================================================

def build_windows(df, sequence_ids):
    """
    Returns X, y_near, y_far, in_leak
    in_leak[i] = True if the window ITSELF already contains leak samples.
    Those windows are trivially positive, so they are reported separately.
    """
    X, y_near, y_far, in_leak = [], [], [], []

    for seq_id in sequence_ids:
        group = df[df["sequence_id"] == seq_id].reset_index(drop=True)
        if len(group) <= WINDOW_SIZE:
            continue

        values = group[FEATURE_COLS].values
        labels = group["label"].values

        for start in range(0, len(group) - WINDOW_SIZE, STRIDE):
            end = start + WINDOW_SIZE

            future_near = labels[end:min(end + NEAR_HORIZON, len(group))]
            future_far = labels[end:min(end + FAR_HORIZON, len(group))]
            if len(future_near) == 0 or len(future_far) == 0:
                continue

            X.append(values[start:end])
            y_near.append(int(future_near.max() > 0))
            y_far.append(int(future_far.max() > 0))
            in_leak.append(bool(labels[start:end].max() > 0))

    return (
        np.array(X, dtype=np.float32),
        np.array(y_near, dtype=np.int32),
        np.array(y_far, dtype=np.int32),
        np.array(in_leak, dtype=bool),
    )


# ============================================================
# METRICS
# ============================================================

def compute_metrics(y_true, prob, threshold=THRESHOLD):
    pred = (prob >= threshold).astype(int)
    out = {
        "n": int(len(y_true)),
        "positives": int(y_true.sum()),
        "precision": precision_score(y_true, pred, zero_division=0),
        "recall": recall_score(y_true, pred, zero_division=0),
        "f1": f1_score(y_true, pred, zero_division=0),
        "confusion_matrix": confusion_matrix(y_true, pred, labels=[0, 1]),
        "pred": pred,
    }
    if len(np.unique(y_true)) == 2:
        out["pr_auc"] = average_precision_score(y_true, prob)
        out["roc_auc"] = roc_auc_score(y_true, prob)
    else:
        out["pr_auc"] = None
        out["roc_auc"] = None
    return out


def fmt(x):
    return "n/a" if x is None else f"{x:.4f}"


def print_metrics(title, y_true, prob):
    m = compute_metrics(y_true, prob)
    print(f"\n--- {title} ---")
    print(f"windows={m['n']}  positives={m['positives']}")
    if m["positives"] == 0:
        print("No positive windows in this subset - metrics not meaningful.")
        return m
    print(f"Precision : {m['precision']:.4f}")
    print(f"Recall    : {m['recall']:.4f}")
    print(f"F1-score  : {m['f1']:.4f}")
    print(f"PR-AUC    : {fmt(m['pr_auc'])}")
    print(f"ROC-AUC   : {fmt(m['roc_auc'])}")
    print("Confusion matrix [[TN FP] [FN TP]]:")
    print(m["confusion_matrix"])
    return m


# ============================================================
# EVALUATE ONE SET OF SEQUENCES
# ============================================================

def predict_probs(model, scaler, X):
    n, w, f = X.shape
    flat = pd.DataFrame(X.reshape(-1, f), columns=FEATURE_COLS)
    scaled = scaler.transform(flat).reshape(n, w, f)

    preds = model.predict(scaled, verbose=0)
    if isinstance(preds, (list, tuple)):
        return np.asarray(preds[0]).reshape(-1), np.asarray(preds[1]).reshape(-1)
    preds = np.asarray(preds)
    if preds.ndim == 2 and preds.shape[1] == 2:
        return preds[:, 0], preds[:, 1]
    raise ValueError(f"Unexpected prediction shape: {preds.shape}")


def evaluate_set(model, scaler, df, ids, label):
    print("\n" + "=" * 70)
    print(f"{label}")
    print("=" * 70)
    print(f"Sequences ({len(ids)}): {ids}")

    X, y_near, y_far, in_leak = build_windows(df, ids)
    print(f"Windows: {len(X)}   already inside a leak: {int(in_leak.sum())}   "
          f"pre-onset/healthy: {int((~in_leak).sum())}")

    p_near, p_far = predict_probs(model, scaler, X)
    pre = ~in_leak

    results = {}
    for name, y, p in (("5-min", y_near, p_near), ("15-min", y_far, p_far)):
        print("\n" + "#" * 70)
        print(f"{name} proxy target")
        print("#" * 70)
        results[(name, "all")] = print_metrics(f"{name}: ALL windows", y, p)
        results[(name, "pre")] = print_metrics(
            f"{name}: PRE-ONSET windows only (real forecasting test)", y[pre], p[pre]
        )

    out = pd.DataFrame({
        "actual_5min": y_near, "probability_5min": p_near,
        "prediction_5min": (p_near >= THRESHOLD).astype(int),
        "actual_15min": y_far, "probability_15min": p_far,
        "prediction_15min": (p_far >= THRESHOLD).astype(int),
        "window_already_in_leak": in_leak,
    })
    return results, out


def summary_line(tag, results):
    parts = []
    for h in ("5-min", "15-min"):
        a, p = results[(h, "all")], results[(h, "pre")]
        parts.append(
            f"{h}: all F1={a['f1']:.3f} recall={a['recall']:.3f} PR-AUC={fmt(a['pr_auc'])} | "
            f"pre-onset recall={p['recall']:.3f} (positives={p['positives']})"
        )
    print(f"{tag}\n   " + "\n   ".join(parts))


# ============================================================
# MAIN
# ============================================================

def main():
    import tensorflow as tf  # imported here so the helpers can be tested without TF

    print("=" * 70)
    print("LSTM EVALUATION (held-out sequences)")
    print("=" * 70)

    df = pd.read_csv(DATA_PATH)
    print(f"Dataset rows: {len(df):,}   sequences: {df['sequence_id'].nunique()}")

    scaler = joblib.load(SCALER_PATH)
    model = tf.keras.models.load_model(MODEL_PATH, compile=False)

    val_ids, source = get_validation_ids(df)
    print(f"\nValidation split source: {source}")

    results, out = evaluate_set(model, scaler, df, val_ids, "VALIDATION SET (use these numbers in the paper)")
    os.makedirs(os.path.dirname(OUTPUT_PATH) or ".", exist_ok=True)
    out.to_csv(OUTPUT_PATH, index=False)
    print(f"\nPredictions saved to {OUTPUT_PATH}")

    old_results = None
    if COMPARE_OLD_SPLIT:
        old_ids = get_old_split_ids(df)
        overlap = len(set(old_ids) & set(val_ids))
        if overlap == 0:
            old_results, _ = evaluate_set(
                model, scaler, df, old_ids,
                "OLD SPLIT (comparison only - probably TRAINING sequences)"
            )
        else:
            print(f"\nOld-split comparison skipped (overlaps validation set by {overlap}).")

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    summary_line("VALIDATION SET", results)
    if old_results is not None:
        summary_line("OLD SPLIT (comparison)", old_results)
        print(
            "\nHow to read this: if the model trained with train_lstm.py's split, the OLD SPLIT\n"
            "scores should look equal or better than the VALIDATION SET (it saw those sequences).\n"
            "If the VALIDATION SET looks better, the saved model was trained with the numpy split\n"
            "instead - then retrain with train_lstm.py and save the IDs (snippet below)."
        )


if __name__ == "__main__":
    main()


# ------------------------------------------------------------------
# ADD THIS TO train_lstm.py (inside train(), right after the split)
# so evaluation can never use a different split again:
#
#     import json
#     os.makedirs("models", exist_ok=True)
#     with open("models/lstm_val_sequence_ids.json", "w") as f:
#         json.dump([int(i) for i in val_seq_ids], f)
# ------------------------------------------------------------------