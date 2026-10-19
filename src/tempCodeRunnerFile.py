import pickle
import joblib
import numpy as np
import pandas as pd
import tensorflow as tf

from sklearn.metrics import (
    precision_score,
    recall_score,
    f1_score,
    average_precision_score,
    confusion_matrix,
    classification_report,
    roc_auc_score
)

# ============================================================
# CONFIGURATION
# ============================================================

DATA_PATH = "data/r32_synthetic_full.csv"
MODEL_PATH = "models/lstm_leak_forecast.h5"
SCALER_PATH = "models/lstm_scaler.pkl"

WINDOW_SIZE = 36
STRIDE = 6

# 10 seconds/sample
# 30 samples = 5 minutes
# 90 samples = 15 minutes
NEAR_HORIZON = 30
FAR_HORIZON = 90

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
    "rolling_std_5min"
]


# ============================================================
# BUILD LSTM WINDOWS
# ============================================================

def build_windows(df, sequence_ids):

    X = []
    y_near = []
    y_far = []

    for seq_id in sequence_ids:

        group = df[df["sequence_id"] == seq_id].copy()
        group = group.reset_index(drop=True)

        values = group[FEATURE_COLS].values
        labels = group["label"].values

        if len(group) <= WINDOW_SIZE:
            continue

        for start in range(
            0,
            len(group) - WINDOW_SIZE,
            STRIDE
        ):

            end = start + WINDOW_SIZE

            window = values[start:end]

            # ------------------------------------------------
            # Future horizons
            # ------------------------------------------------

            near_end = min(
                end + NEAR_HORIZON,
                len(group)
            )

            far_end = min(
                end + FAR_HORIZON,
                len(group)
            )

            future_near = labels[end:near_end]
            future_far = labels[end:far_end]

            if len(future_near) == 0 or len(future_far) == 0:
                continue

            # Leak occurs within future horizon
            target_near = int(np.max(future_near) > 0)
            target_far = int(np.max(future_far) > 0)

            X.append(window)
            y_near.append(target_near)
            y_far.append(target_far)

    return (
        np.array(X, dtype=np.float32),
        np.array(y_near, dtype=np.int32),
        np.array(y_far, dtype=np.int32)
    )


# ============================================================
# METRIC EVALUATION
# ============================================================

def evaluate_target(
    name,
    y_true,
    y_probability,
    y_prediction
):

    print("\n")
    print("=" * 70)
    print(name)
    print("=" * 70)

    precision = precision_score(
        y_true,
        y_prediction,
        zero_division=0
    )

    recall = recall_score(
        y_true,
        y_prediction,
        zero_division=0
    )

    f1 = f1_score(
        y_true,
        y_prediction,
        zero_division=0
    )

    pr_auc = average_precision_score(
        y_true,
        y_probability
    )

    print(f"\nPrecision : {precision:.4f}")
    print(f"Recall    : {recall:.4f}")
    print(f"F1-score  : {f1:.4f}")
    print(f"PR-AUC    : {pr_auc:.4f}")

    # --------------------------------------------------------
    # ROC-AUC
    # --------------------------------------------------------

    try:

        roc_auc = roc_auc_score(
            y_true,
            y_probability
        )

        print(f"ROC-AUC   : {roc_auc:.4f}")

    except ValueError:

        print("ROC-AUC   : Not available")

    # --------------------------------------------------------
    # Classification report
    # --------------------------------------------------------

    print("\nClassification Report:")

    print(
        classification_report(
            y_true,
            y_prediction,
            target_names=[
                "No Leak",
                "Leak"
            ],
            zero_division=0
        )
    )

    # --------------------------------------------------------
    # Confusion matrix
    # --------------------------------------------------------

    cm = confusion_matrix(
        y_true,
        y_prediction
    )

    print("Confusion Matrix:")
    print(cm)

    print("\nConfusion Matrix format:")
    print("[[TN FP]")
    print(" [FN TP]]")

    print("\nActual positive samples:", int(np.sum(y_true)))
    print(
        "Actual negative samples:",
        int(np.sum(y_true == 0))
    )

    print(
        "Predicted positive samples:",
        int(np.sum(y_prediction))
    )

    print(
        "Predicted negative samples:",
        int(np.sum(y_prediction == 0))
    )

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "pr_auc": pr_auc,
        "roc_auc": roc_auc if "roc_auc" in locals() else None,
        "confusion_matrix": cm
    }


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print("LSTM EVALUATION")
    print("=" * 70)

    # ========================================================
    # LOAD DATASET
    # ========================================================

    print("\nLoading dataset...")

    df = pd.read_csv(DATA_PATH)

    print(f"Dataset rows: {len(df):,}")
    print(f"Sequences: {df['sequence_id'].nunique()}")

    # ========================================================
    # SEQUENCE-LEVEL SPLIT
    # ========================================================

    sequence_ids = sorted(
        df["sequence_id"].unique()
    )

    np.random.seed(42)

    shuffled_ids = np.random.permutation(
        sequence_ids
    )

    split_index = int(
        0.80 * len(shuffled_ids)
    )

    train_ids = sorted(
        shuffled_ids[:split_index]
    )

    val_ids = sorted(
        shuffled_ids[split_index:]
    )

    print("\nSequence split:")
    print(
        f"Training sequences:   {len(train_ids)}"
    )

    print(
        f"Validation sequences: {len(val_ids)}"
    )

    print("\nValidation sequence IDs:")
    print(val_ids)

    # ========================================================
    # LOAD SCALER
    # ========================================================

    print("\nLoading scaler...")

    # Your scaler was saved in joblib-compatible format.
    # Therefore use joblib.load() instead of pickle.load().

    scaler = joblib.load(
        SCALER_PATH
    )

    print("Scaler loaded successfully.")

    # ========================================================
    # BUILD VALIDATION WINDOWS
    # ========================================================

    print("\nBuilding validation windows...")

    X_val, y_near, y_far = build_windows(
        df,
        val_ids
    )

    print("\nValidation windows:")
    print(f"X shape: {X_val.shape}")
    print(f"Near target shape: {y_near.shape}")
    print(f"Far target shape:  {y_far.shape}")

    # ========================================================
    # SCALE VALIDATION DATA
    # ========================================================

    original_shape = X_val.shape

    X_val_2d = X_val.reshape(
        -1,
        len(FEATURE_COLS)
    )

    X_val_scaled = scaler.transform(
        X_val_2d
    )

    X_val_scaled = X_val_scaled.reshape(
        original_shape
    )

    print(
        f"Scaled validation shape: {X_val_scaled.shape}"
    )

    # ========================================================
    # LOAD LSTM
    # ========================================================

    print("\nLoading LSTM model...")

    model = tf.keras.models.load_model(
        MODEL_PATH,
        compile=False
    )

    print("Model loaded successfully.")

    # ========================================================
    # GENERATE PREDICTIONS
    # ========================================================

    print("\nGenerating predictions...")

    predictions = model.predict(
        X_val_scaled,
        verbose=1
    )

    # ========================================================
    # HANDLE MULTI-OUTPUT MODEL
    # ========================================================

    if isinstance(predictions, list):

        pred_near = predictions[0].reshape(-1)
        pred_far = predictions[1].reshape(-1)

    else:

        predictions = np.asarray(
            predictions
        )

        if (
            predictions.ndim == 2
            and predictions.shape[1] == 2
        ):

            pred_near = predictions[:, 0]
            pred_far = predictions[:, 1]

        else:

            raise ValueError(
                f"Unexpected prediction shape: "
                f"{predictions.shape}"
            )

    print(
        f"\nPrediction count: {len(pred_near)}"
    )

    # ========================================================
    # CONVERT PROBABILITIES TO CLASSES
    # ========================================================

    THRESHOLD = 0.5

    pred_near_class = (
        pred_near >= THRESHOLD
    ).astype(int)

    pred_far_class = (
        pred_far >= THRESHOLD
    ).astype(int)

    # ========================================================
    # EVALUATE 5-MINUTE TARGET
    # ========================================================

    near_results = evaluate_target(
        "5-MINUTE PROXY FORECAST",
        y_near,
        pred_near,
        pred_near_class
    )

    # ========================================================
    # EVALUATE 15-MINUTE TARGET
    # ========================================================

    far_results = evaluate_target(
        "15-MINUTE PROXY FORECAST",
        y_far,
        pred_far,
        pred_far_class
    )

    # ========================================================
    # SAVE PREDICTIONS
    # ========================================================

    results_df = pd.DataFrame({

        "actual_5min": y_near,

        "probability_5min": pred_near,

        "prediction_5min": pred_near_class,

        "actual_15min": y_far,

        "probability_15min": pred_far,

        "prediction_15min": pred_far_class
    })

    output_path = (
        "data/lstm_validation_predictions.csv"
    )

    results_df.to_csv(
        output_path,
        index=False
    )

    # ========================================================
    # FINAL SUMMARY
    # ========================================================

    print("\n")
    print("=" * 70)
    print("EVALUATION COMPLETE")
    print("=" * 70)

    print(
        f"\nPredictions saved to: "
        f"{output_path}"
    )

    print("\nFinal Summary:")

    print(
        f"5-min  → "
        f"Precision={near_results['precision']:.4f}, "
        f"Recall={near_results['recall']:.4f}, "
        f"F1={near_results['f1']:.4f}, "
        f"PR-AUC={near_results['pr_auc']:.4f}"
    )

    print(
        f"15-min → "
        f"Precision={far_results['precision']:.4f}, "
        f"Recall={far_results['recall']:.4f}, "
        f"F1={far_results['f1']:.4f}, "
        f"PR-AUC={far_results['pr_auc']:.4f}"
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()