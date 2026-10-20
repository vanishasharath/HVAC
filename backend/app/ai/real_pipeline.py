"""
End-to-End AI Inference Pipeline
================================

Connects the three trained HVAC leak-detection models:

1. Isolation Forest
   -> Detects whether the current sensor reading is anomalous.

2. LSTM
   -> Uses the recent 36-reading history to estimate leak probability
      for approximately the next 24 hours and 48 hours.

3. Random Forest
   -> Combines sensor features, anomaly information, and LSTM probabilities
      to produce the final severity:
      Low / Medium / High / Critical.

This module is designed to be called by the FastAPI backend.
"""

import numpy as np
import pandas as pd
import tensorflow as tf
import joblib

from collections import deque
from pathlib import Path


# ============================================================
# CONFIGURATION
# ============================================================

# These MUST match the features used during model training.
SENSOR_COLS = [
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

# Raw sensor columns coming from the edge/device.
EDGE_COLS = [
    "gas_ppm",
    "pressure",
    "temperature",
    "humidity",
    "compressor_current",
]

# LSTM requires the most recent 36 readings.
LSTM_WINDOW_SIZE = 36

# 30 samples × 10 seconds = approximately 5 minutes.
ROLLING_WINDOW = 30

SEVERITY_LEVELS = [
    "Low",
    "Medium",
    "High",
    "Critical",
]


# ============================================================
# LEAK DETECTION PIPELINE
# ============================================================

class LeakDetectionPipeline:

    def __init__(self, models_dir=None):
        """
        Load all trained AI models.

        By default, models are loaded from:

        backend/
        └── app/
            └── ai/
                └── models/

        This makes the code independent of the directory from which
        Python is executed.
        """

        print("Loading models...")

        # ----------------------------------------------------
        # Correct model directory
        # ----------------------------------------------------

        if models_dir is None:
            models_dir = Path(__file__).resolve().parent / "models"
        else:
            models_dir = Path(models_dir)

        print(f"Model directory: {models_dir}")

        # ----------------------------------------------------
        # Verify model directory exists
        # ----------------------------------------------------

        if not models_dir.exists():
            raise FileNotFoundError(
                f"Model directory does not exist: {models_dir}"
            )

        # ----------------------------------------------------
        # Model file paths
        # ----------------------------------------------------

        isolation_forest_path = (
            models_dir / "isolation_forest_r32.pkl"
        )

        lstm_model_path = (
            models_dir / "lstm_leak_forecast.h5"
        )

        lstm_scaler_path = (
            models_dir / "lstm_scaler.pkl"
        )

        random_forest_path = (
            models_dir / "random_forest_severity.pkl"
        )

        # ----------------------------------------------------
        # Verify all model files exist
        # ----------------------------------------------------

        required_files = [
            isolation_forest_path,
            lstm_model_path,
            lstm_scaler_path,
            random_forest_path,
        ]

        for model_file in required_files:
            if not model_file.exists():
                raise FileNotFoundError(
                    f"Required model file not found: {model_file}"
                )

        # ----------------------------------------------------
        # Load Isolation Forest
        # ----------------------------------------------------

        self.isolation_forest = joblib.load(
            isolation_forest_path
        )

        # ----------------------------------------------------
        # Load LSTM
        # ----------------------------------------------------

        self.lstm_model = tf.keras.models.load_model(
            lstm_model_path
        )

        # ----------------------------------------------------
        # Load LSTM scaler
        # ----------------------------------------------------

        self.lstm_scaler = joblib.load(
            lstm_scaler_path
        )

        # ----------------------------------------------------
        # Load Random Forest
        # ----------------------------------------------------

        self.rf_model = joblib.load(
            random_forest_path
        )

        print("Isolation Forest loaded.")
        print("LSTM model loaded.")
        print("LSTM scaler loaded.")
        print("Random Forest loaded.")
        print("All models loaded successfully.\n")


    # ========================================================
    # SINGLE READING PREDICTION
    # ========================================================

    def predict_single_row(
        self,
        feature_row,
        lstm_window,
        anomaly_duration_so_far,
    ):
        """
        Run one sensor reading through the complete AI pipeline.

        Parameters
        ----------
        feature_row:
            Dictionary or pandas Series containing all 10 SENSOR_COLS.

        lstm_window:
            Array containing the most recent 36 readings.

            Shape:
                (36, 10)

            If fewer than 36 readings are available,
            pass None.

        anomaly_duration_so_far:
            Number of consecutive anomalous readings before
            the current reading.

        Returns
        -------
        dict
            AI prediction results.
        """

        # ====================================================
        # Validate input
        # ====================================================

        missing_columns = [
            col for col in SENSOR_COLS
            if col not in feature_row
        ]

        if missing_columns:
            raise ValueError(
                f"Missing required feature columns: "
                f"{missing_columns}"
            )

        # ====================================================
        # STAGE 1 — ISOLATION FOREST
        # ====================================================

        X_if = pd.DataFrame(
            [feature_row]
        )[SENSOR_COLS]

        # Isolation Forest anomaly score.
        #
        # The trained model's decision_function becomes more
        # negative for anomalous samples, so we invert it.
        anomaly_score = (
            -self.isolation_forest
            .decision_function(X_if)[0]
        )

        # Isolation Forest prediction:
        #
        #  1  = normal
        # -1  = anomaly

        anomaly_prediction = (
            self.isolation_forest.predict(X_if)[0]
        )

        anomaly_flag = (
            1
            if anomaly_prediction == -1
            else 0
        )

        # ====================================================
        # ANOMALY DURATION
        # ====================================================

        if anomaly_flag:
            anomaly_duration = (
                anomaly_duration_so_far + 1
            )
        else:
            anomaly_duration = 0

        # ====================================================
        # STAGE 2 — LSTM
        # ====================================================

        if lstm_window is not None:

            # Convert window into DataFrame so that the
            # feature ordering is guaranteed.
            lstm_window_df = pd.DataFrame(
                lstm_window,
                columns=SENSOR_COLS,
            )

            # Scale using the SAME scaler used during training.
            scaled_window = (
                self.lstm_scaler.transform(
                    lstm_window_df
                )
            )

            # Reshape for Keras LSTM.
            #
            # Required shape:
            # (batch_size, time_steps, features)
            #
            # = (1, 36, 10)

            X_lstm = scaled_window.reshape(
                1,
                LSTM_WINDOW_SIZE,
                len(SENSOR_COLS),
            )

            # Run LSTM.
            lstm_prediction = (
                self.lstm_model.predict(
                    X_lstm,
                    verbose=0,
                )
            )

            # Two output heads:
            #
            # output 1 = 24-hour probability
            # output 2 = 48-hour probability

            prob_24hr = float(
                lstm_prediction[0][0][0]
            )

            prob_48hr = float(
                lstm_prediction[1][0][0]
            )

        else:

            # Not enough history for the LSTM.
            prob_24hr = 0.0
            prob_48hr = 0.0

        # ====================================================
        # STAGE 3 — RANDOM FOREST
        # ====================================================

        rf_features = pd.DataFrame([
            {
                # Original 10 sensor features
                **{
                    col: feature_row[col]
                    for col in SENSOR_COLS
                },

                # Isolation Forest information
                "anomaly_score": anomaly_score,
                "anomaly_flag": anomaly_flag,
                "anomaly_duration": anomaly_duration,

                # LSTM information
                "lstm_prob_24hr": prob_24hr,
                "lstm_prob_48hr": prob_48hr,
            }
        ])

        # Final severity prediction.
        severity = self.rf_model.predict(
            rf_features
        )[0]

        # Probability for each severity class.
        severity_probabilities = (
            self.rf_model.predict_proba(
                rf_features
            )[0]
        )

        severity_proba = dict(
            zip(
                self.rf_model.classes_,
                severity_probabilities,
            )
        )

        severity_confidence = severity_proba.get(
            severity,
            0.0,
        )

        # ====================================================
        # RETURN RESULT
        # ====================================================

        return {
            "anomaly_score": round(
                float(anomaly_score),
                4,
            ),

            "anomaly_flag": int(
                anomaly_flag
            ),

            "anomaly_duration": int(
                anomaly_duration
            ),

            "lstm_prob_24hr": round(
                float(prob_24hr),
                4,
            ),

            "lstm_prob_48hr": round(
                float(prob_48hr),
                4,
            ),

            "severity": str(
                severity
            ),

            "severity_confidence": round(
                float(severity_confidence),
                4,
            ),
        }


# ============================================================
# SENSOR STREAM
# ============================================================

class SensorStream:
    """
    Maintains streaming state for one HVAC unit.

    The stream maintains:

    1. A rolling 36-reading buffer for the LSTM.
    2. A consecutive anomaly-duration counter for the
       Random Forest.

    In a production system, this state can eventually be
    stored per HVAC unit in Redis or another state store.
    """

    def __init__(
        self,
        pipeline: LeakDetectionPipeline,
    ):
        self.pipeline = pipeline

        # Keep only the latest 36 readings.
        self.buffer = deque(
            maxlen=LSTM_WINDOW_SIZE
        )

        # Consecutive anomaly counter.
        self.anomaly_duration = 0


    def push_reading(self, feature_row):
        """
        Push one feature-engineered sensor reading
        through the AI pipeline.
        """

        # Add current reading to rolling buffer.
        self.buffer.append(
            [
                feature_row[col]
                for col in SENSOR_COLS
            ]
        )

        # LSTM only runs after 36 readings exist.
        if len(self.buffer) == LSTM_WINDOW_SIZE:
            lstm_window = np.array(
                self.buffer,
                dtype=float,
            )
        else:
            lstm_window = None

        # Run complete pipeline.
        result = self.pipeline.predict_single_row(
            feature_row,
            lstm_window,
            self.anomaly_duration,
        )

        # Update anomaly duration for next reading.
        self.anomaly_duration = (
            result["anomaly_duration"]
        )

        return result


# ============================================================
# DEMO
# ============================================================

def demo():
    """
    Run the complete pipeline against a synthetic HVAC
    sequence.

    This is useful for demonstrating the AI pipeline
    during the project presentation/viva.
    """

    print("=" * 70)
    print("HVAC LEAK DETECTION — AI PIPELINE DEMO")
    print("=" * 70)
    print()

    # --------------------------------------------------------
    # Load pipeline
    # --------------------------------------------------------

    pipeline = LeakDetectionPipeline()

    # --------------------------------------------------------
    # Load synthetic dataset
    # --------------------------------------------------------

    # Locate data relative to this project.
    #
    # real_pipeline.py is:
    # backend/app/ai/real_pipeline.py
    #
    # Project root:
    # backend/
    #
    project_root = (
        Path(__file__).resolve()
        .parents[2]
    )

    data_path = (
        project_root
        / "data"
        / "r32_synthetic_full.csv"
    )

    if not data_path.exists():

        print(
            f"Dataset not found at:\n"
            f"{data_path}\n"
        )

        print(
            "The model loading test can still be "
            "performed without the demo dataset."
        )

        return

    df = pd.read_csv(data_path)

    # --------------------------------------------------------
    # Find a critical sequence
    # --------------------------------------------------------

    critical_seqs = (
        df[
            df["severity"].astype(str).str.lower()
            == "critical"
        ]["sequence_id"]
        .unique()
    )

    if len(critical_seqs) == 0:

        print(
            "No critical sequence found in dataset."
        )

        return

    demo_seq_id = critical_seqs[0]

    seq_df = (
        df[
            df["sequence_id"]
            == demo_seq_id
        ]
        .reset_index(drop=True)
    )

    print(
        f"Running pipeline on "
        f"sequence_id={demo_seq_id}"
    )

    print(
        f"Total readings: {len(seq_df)}\n"
    )

    # --------------------------------------------------------
    # Output header
    # --------------------------------------------------------

    print(
        f"{'row':>4} "
        f"{'true_label':>10} "
        f"{'anomaly':>8} "
        f"{'dur':>5} "
        f"{'p24hr':>7} "
        f"{'p48hr':>7} "
        f"{'severity':>10}"
    )

    print("-" * 70)

    # --------------------------------------------------------
    # Create stream
    # --------------------------------------------------------

    stream = SensorStream(
        pipeline
    )

    # --------------------------------------------------------
    # Process every reading
    # --------------------------------------------------------

    for i, row in seq_df.iterrows():

        result = stream.push_reading(
            row
        )

        # Print every 20th row and the final row.
        if (
            i % 20 == 0
            or i == len(seq_df) - 1
        ):

            print(
                f"{i:>4} "
                f"{str(row['label']):>10} "
                f"{result['anomaly_flag']:>8} "
                f"{result['anomaly_duration']:>5} "
                f"{result['lstm_prob_24hr']:>7.3f} "
                f"{result['lstm_prob_48hr']:>7.3f} "
                f"{result['severity']:>10}"
            )

    print()
    print("=" * 70)
    print("AI PIPELINE DEMO COMPLETE")
    print("=" * 70)


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    demo()