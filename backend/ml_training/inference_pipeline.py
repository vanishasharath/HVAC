"""
End-to-End Inference Pipeline
==============================
Ties together all three cloud AI models into the flow your FastAPI backend
will eventually implement:

  1. Isolation Forest  -> is this moment anomalous? (anomaly_score, anomaly_flag)
  2. LSTM               -> given recent history, what's the leak probability
                            in the next ~24hr / ~48hr window?
  3. Random Forest       -> combining everything (raw sensors + IF + LSTM +
                            anomaly duration), what's the final severity?
                            (Low / Medium / High / Critical)

This mirrors what happens in production: a stream of sensor readings comes
in, and the system needs to maintain a rolling window of recent history per
unit (for the LSTM) and a running anomaly-duration counter (for RF) - both
of which reset when a new "session" starts. The SensorStream class below
handles that state, so this looks like what real deployment code would do,
not just a one-off script.
"""

import numpy as np
import pandas as pd
import tensorflow as tf
import joblib
from collections import deque

# --- Config: must match the training scripts exactly ---
SENSOR_COLS = [
    "gas_ppm", "pressure", "temperature", "humidity", "compressor_current",
    "gas_ppm_rate_of_change", "pressure_rate_of_change", "compressor_current_rate_of_change",
    "rolling_mean_5min", "rolling_std_5min",
]
EDGE_COLS = ["gas_ppm", "pressure", "temperature", "humidity", "compressor_current"]
LSTM_WINDOW_SIZE = 36
ROLLING_WINDOW = 30  # matches add_derived_features() in generate_synthetic_data.py

SEVERITY_LEVELS = ["Low", "Medium", "High", "Critical"]


class LeakDetectionPipeline:
    def __init__(self, models_dir="models"):
        print("Loading models...")
        self.isolation_forest = joblib.load(f"{models_dir}/isolation_forest_r32.pkl")
        self.lstm_model = tf.keras.models.load_model(f"{models_dir}/lstm_leak_forecast.h5")
        self.lstm_scaler = joblib.load(f"{models_dir}/lstm_scaler.pkl")
        self.rf_model = joblib.load(f"{models_dir}/random_forest_severity.pkl")
        print("All models loaded.\n")

    def predict_single_row(self, feature_row, lstm_window, anomaly_duration_so_far):
        """
        Runs one row through the full cloud pipeline.

        feature_row: dict or Series with all SENSOR_COLS values for THIS moment
        lstm_window: array of shape (LSTM_WINDOW_SIZE, len(SENSOR_COLS)) - the
                     last N readings including this one, in order. If fewer
                     than LSTM_WINDOW_SIZE readings exist yet, pass None -
                     LSTM probabilities will default to 0.0 (not enough history).
        anomaly_duration_so_far: int - how many consecutive prior readings
                     were anomalous (the caller/SensorStream tracks this)
        """
        X_if = pd.DataFrame([feature_row])[SENSOR_COLS]

        # --- Stage 1: Isolation Forest ---
        anomaly_score = -self.isolation_forest.decision_function(X_if)[0]
        anomaly_flag = 1 if self.isolation_forest.predict(X_if)[0] == -1 else 0

        # anomaly_duration includes this row if it's anomalous
        anomaly_duration = anomaly_duration_so_far + 1 if anomaly_flag else 0

        # --- Stage 2: LSTM ---
        if lstm_window is not None:
            lstm_window_df = pd.DataFrame(lstm_window, columns=SENSOR_COLS)
            scaled_window = self.lstm_scaler.transform(lstm_window_df)
            X_lstm = scaled_window.reshape(1, LSTM_WINDOW_SIZE, len(SENSOR_COLS))
            prob_24hr, prob_48hr = self.lstm_model.predict(X_lstm, verbose=0)
            prob_24hr, prob_48hr = float(prob_24hr[0][0]), float(prob_48hr[0][0])
        else:
            prob_24hr, prob_48hr = 0.0, 0.0

        # --- Stage 3: Random Forest (final severity decision) ---
        rf_features = pd.DataFrame([{
            **{col: feature_row[col] for col in SENSOR_COLS},
            "anomaly_score": anomaly_score,
            "anomaly_flag": anomaly_flag,
            "anomaly_duration": anomaly_duration,
            "lstm_prob_24hr": prob_24hr,
            "lstm_prob_48hr": prob_48hr,
        }])
        severity = self.rf_model.predict(rf_features)[0]
        severity_proba = dict(zip(self.rf_model.classes_, self.rf_model.predict_proba(rf_features)[0]))

        return {
            "anomaly_score": round(anomaly_score, 4),
            "anomaly_flag": anomaly_flag,
            "anomaly_duration": anomaly_duration,
            "lstm_prob_24hr": round(prob_24hr, 4),
            "lstm_prob_48hr": round(prob_48hr, 4),
            "severity": severity,
            "severity_confidence": round(severity_proba[severity], 4),
        }


class SensorStream:
    """
    Simulates what a real deployment maintains per HVAC unit: a rolling
    buffer of recent readings (for the LSTM) and a running anomaly-duration
    counter (for RF). In production this state would live per-unit in Redis
    or similar - here it's just an in-memory deque for demonstration.
    """
    def __init__(self, pipeline: LeakDetectionPipeline):
        self.pipeline = pipeline
        self.buffer = deque(maxlen=LSTM_WINDOW_SIZE)
        self.anomaly_duration = 0

    def push_reading(self, feature_row):
        self.buffer.append([feature_row[col] for col in SENSOR_COLS])

        lstm_window = np.array(self.buffer) if len(self.buffer) == LSTM_WINDOW_SIZE else None

        result = self.pipeline.predict_single_row(
            feature_row, lstm_window, self.anomaly_duration
        )
        self.anomaly_duration = result["anomaly_duration"]
        return result


def demo():
    """
    Walks through one real synthetic sequence (a leak progressing from
    healthy to critical) row by row through the pipeline, printing the
    severity decision at each step - this is what you'd screenshot/demo
    for your viva.
    """
    pipeline = LeakDetectionPipeline()

    df = pd.read_csv("data/r32_synthetic_full.csv")

    # Pick one leak sequence that reaches "critical" for a clear demo
    critical_seqs = df[df["severity"] == "critical"]["sequence_id"].unique()
    demo_seq_id = critical_seqs[0]
    seq_df = df[df["sequence_id"] == demo_seq_id].reset_index(drop=True)

    print(f"Running pipeline on sequence_id={demo_seq_id} ({len(seq_df)} readings)\n")
    print(f"{'row':>4} {'true_label':>10} {'anomaly':>8} {'dur':>5} {'p24hr':>7} {'p48hr':>7} {'severity':>10}")
    print("-" * 65)

    stream = SensorStream(pipeline)

    # Print every 20th row so the demo output isn't overwhelming
    for i, row in seq_df.iterrows():
        result = stream.push_reading(row)
        if i % 20 == 0 or i == len(seq_df) - 1:
            print(f"{i:>4} {row['label']:>10} {result['anomaly_flag']:>8} "
                  f"{result['anomaly_duration']:>5} {result['lstm_prob_24hr']:>7.3f} "
                  f"{result['lstm_prob_48hr']:>7.3f} {result['severity']:>10}")


if __name__ == "__main__":
    demo()