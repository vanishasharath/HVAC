import os
import pickle
from collections import deque

import numpy as np
import pandas as pd
import tensorflow as tf
import joblib

from sklearn.ensemble import IsolationForest


# ============================================================
# CONFIGURATION
# ============================================================

DATA_PATH = "data/r32_synthetic_full.csv"

IF_MODEL_PATH = "models/isolation_forest_r32.pkl"
LSTM_MODEL_PATH = "models/lstm_leak_forecast.h5"
LSTM_SCALER_PATH = "models/lstm_scaler.pkl"
RF_MODEL_PATH = "models/random_forest_severity.pkl"

WINDOW_SIZE = 36

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

RAW_COLS = [
    "gas_ppm",
    "pressure",
    "temperature",
    "humidity",
    "compressor_current"
]


# ============================================================
# LOAD MODELS
# ============================================================

def load_models():

    print("\nLoading models...")

    if_model = joblib.load(IF_MODEL_PATH)

    lstm_model = tf.keras.models.load_model(
        LSTM_MODEL_PATH,
        compile=False
    )

    scaler = joblib.load(
        LSTM_SCALER_PATH
    )

    rf_model = joblib.load(
        RF_MODEL_PATH
    )

    print("All models loaded successfully.")

    return (
        if_model,
        lstm_model,
        scaler,
        rf_model
    )


# ============================================================
# FEATURE ENGINEERING
# ============================================================

def calculate_features(history):

    df = pd.DataFrame(
        history,
        columns=RAW_COLS
    )

    # --------------------------------------------------------
    # Rate of change
    # --------------------------------------------------------

    df["gas_ppm_rate_of_change"] = (
        df["gas_ppm"].diff()
    )

    df["pressure_rate_of_change"] = (
        df["pressure"].diff()
    )

    df["compressor_current_rate_of_change"] = (
        df["compressor_current"].diff()
    )

    # First value has no previous sample
    df[
        [
            "gas_ppm_rate_of_change",
            "pressure_rate_of_change",
            "compressor_current_rate_of_change"
        ]
    ] = df[
        [
            "gas_ppm_rate_of_change",
            "pressure_rate_of_change",
            "compressor_current_rate_of_change"
        ]
    ].fillna(0)

    # --------------------------------------------------------
    # Rolling statistics
    #
    # 30 samples × 10 seconds = 5 minutes
    # --------------------------------------------------------

    df["rolling_mean_5min"] = (
        df["gas_ppm"]
        .rolling(window=30, min_periods=1)
        .mean()
    )

    df["rolling_std_5min"] = (
        df["gas_ppm"]
        .rolling(window=30, min_periods=1)
        .std()
        .fillna(0)
    )

    return df


# ============================================================
# SINGLE PIPELINE STEP
# ============================================================

def run_pipeline_step(
    history,
    if_model,
    lstm_model,
    scaler,
    rf_model,
    anomaly_duration
):

    feature_df = calculate_features(history)

    current_features = feature_df.iloc[-1]

    # ========================================================
    # ISOLATION FOREST
    # ========================================================

    if_features = current_features[
        FEATURE_COLS
    ].values.reshape(1, -1)

    anomaly_prediction = if_model.predict(
        if_features
    )[0]

    anomaly_score = float(
        -if_model.decision_function(
            if_features
        )[0]
    )

    anomaly_flag = int(
        anomaly_prediction == -1
    )

    # Update anomaly duration
    if anomaly_flag == 1:
        anomaly_duration += 1
    else:
        anomaly_duration = 0

    # ========================================================
    # LSTM
    # ========================================================

    lstm_prob_24hr = 0.0
    lstm_prob_48hr = 0.0

    if len(feature_df) >= WINDOW_SIZE:

        lstm_window = feature_df[
            FEATURE_COLS
        ].tail(WINDOW_SIZE).values

        original_shape = lstm_window.shape

        lstm_window_2d = lstm_window.reshape(
            -1,
            len(FEATURE_COLS)
        )

        lstm_window_scaled = scaler.transform(
            lstm_window_2d
        )

        lstm_window_scaled = (
            lstm_window_scaled.reshape(
                1,
                WINDOW_SIZE,
                len(FEATURE_COLS)
            )
        )

        prediction = lstm_model.predict(
            lstm_window_scaled,
            verbose=0
        )

        if isinstance(prediction, list):

            lstm_prob_24hr = float(
                prediction[0][0][0]
            )

            lstm_prob_48hr = float(
                prediction[1][0][0]
            )

        else:

            prediction = np.asarray(
                prediction
            )

            lstm_prob_24hr = float(
                prediction[0][0]
            )

            lstm_prob_48hr = float(
                prediction[0][1]
            )

    # ========================================================
    # RANDOM FOREST
    # ========================================================

    rf_features = np.array([
        current_features["gas_ppm"],
        current_features["pressure"],
        current_features["temperature"],
        current_features["humidity"],
        current_features["compressor_current"],
        current_features["gas_ppm_rate_of_change"],
        current_features["pressure_rate_of_change"],
        current_features["compressor_current_rate_of_change"],
        current_features["rolling_mean_5min"],
        current_features["rolling_std_5min"],
        anomaly_score,
        anomaly_flag,
        anomaly_duration,
        lstm_prob_24hr,
        lstm_prob_48hr
    ]).reshape(1, -1)

    severity_prediction = rf_model.predict(
        rf_features
    )[0]

    # Probability
    probabilities = rf_model.predict_proba(
        rf_features
    )[0]

    class_names = rf_model.classes_

    probability_dict = {
        str(class_name): float(probability)
        for class_name, probability
        in zip(class_names, probabilities)
    }

    return {
        "anomaly": anomaly_flag,
        "anomaly_score": anomaly_score,
        "anomaly_duration": anomaly_duration,
        "lstm_5min": lstm_prob_24hr,
        "lstm_15min": lstm_prob_48hr,
        "severity": severity_prediction,
        "severity_probabilities": probability_dict
    }, anomaly_duration


# ============================================================
# SCENARIO GENERATORS
# ============================================================

def generate_healthy():

    base = np.array([
        5.0,
        165.0,
        7.0,
        55.0,
        6.0
    ])

    noise = np.array([
        0.8,
        2.0,
        0.5,
        3.0,
        0.3
    ])

    samples = []

    rng = np.random.default_rng(10)

    for _ in range(120):

        reading = (
            base
            + rng.normal(
                0,
                noise
            )
        )

        samples.append(reading)

    return samples


def generate_leak(rate):

    base = np.array([
        5.0,
        165.0,
        7.0,
        55.0,
        6.0
    ])

    noise = np.array([
        0.8,
        2.0,
        0.5,
        3.0,
        0.3
    ])

    samples = []

    rng = np.random.default_rng(20)

    for i in range(120):

        progress = max(
            0,
            i - 20
        )

        gas_increase = (
            progress * rate * 8
        )

        pressure_drop = (
            progress * rate * 1.2
        )

        temperature_change = (
            progress * rate * 0.16
        )

        current_change = (
            progress * rate * 0.07
        )

        reading = np.array([
            base[0] + gas_increase,
            base[1] - pressure_drop,
            base[2] + temperature_change,
            base[3],
            base[4] + current_change
        ])

        reading += rng.normal(
            0,
            noise
        )

        samples.append(reading)

    return samples


# ============================================================
# RUN SCENARIO
# ============================================================

def run_scenario(
    scenario_name,
    samples,
    if_model,
    lstm_model,
    scaler,
    rf_model
):

    print("\n")
    print("=" * 80)
    print(f"SCENARIO: {scenario_name}")
    print("=" * 80)

    history = deque(
        maxlen=WINDOW_SIZE
    )

    anomaly_duration = 0

    results = []

    for index, sample in enumerate(samples):

        history.append(sample)

        result, anomaly_duration = (
            run_pipeline_step(
                list(history),
                if_model,
                lstm_model,
                scaler,
                rf_model,
                anomaly_duration
            )
        )

        results.append(result)

        # Print every 10 samples
        if (
            index % 10 == 0
            or index == len(samples) - 1
        ):

            print(
                f"{index:3d} | "
                f"Anomaly={result['anomaly']} | "
                f"Duration={result['anomaly_duration']:3d} | "
                f"5min={result['lstm_5min']:.3f} | "
                f"15min={result['lstm_15min']:.3f} | "
                f"Severity={result['severity']}"
            )

    # ========================================================
    # SUMMARY
    # ========================================================

    print("\n--- Scenario Summary ---")

    anomaly_count = sum(
        r["anomaly"] for r in results
    )

    severities = [
        str(r["severity"])
        for r in results
    ]

    severity_counts = pd.Series(
        severities
    ).value_counts()

    print(
        f"Anomalous samples: "
        f"{anomaly_count}/{len(results)}"
    )

    print("\nSeverity counts:")

    print(
        severity_counts
    )

    print(
        f"\nFinal LSTM 5-min probability: "
        f"{results[-1]['lstm_5min']:.4f}"
    )

    print(
        f"Final LSTM 15-min probability: "
        f"{results[-1]['lstm_15min']:.4f}"
    )

    print(
        f"Final severity: "
        f"{results[-1]['severity']}"
    )

    return results


# ============================================================
# INSUFFICIENT HISTORY TEST
# ============================================================

def test_insufficient_history(
    if_model,
    lstm_model,
    scaler,
    rf_model
):

    print("\n")
    print("=" * 80)
    print("SCENARIO: INSUFFICIENT HISTORY")
    print("=" * 80)

    samples = generate_healthy()

    history = samples[:20]

    anomaly_duration = 0

    result, anomaly_duration = (
        run_pipeline_step(
            history,
            if_model,
            lstm_model,
            scaler,
            rf_model,
            anomaly_duration
        )
    )

    print(
        f"Available samples: {len(history)}"
    )

    print(
        f"Required LSTM samples: "
        f"{WINDOW_SIZE}"
    )

    print(
        f"LSTM 5-min probability: "
        f"{result['lstm_5min']:.4f}"
    )

    print(
        f"LSTM 15-min probability: "
        f"{result['lstm_15min']:.4f}"
    )

    print(
        f"Final severity: "
        f"{result['severity']}"
    )

    print(
        "\nInsufficient-history test completed "
        "without crashing."
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 80)
    print("END-TO-END AI PIPELINE TEST")
    print("=" * 80)

    # --------------------------------------------------------
    # Load models
    # --------------------------------------------------------

    (
        if_model,
        lstm_model,
        scaler,
        rf_model
    ) = load_models()

    # ========================================================
    # 1. HEALTHY
    # ========================================================

    healthy_results = run_scenario(
        "HEALTHY",
        generate_healthy(),
        if_model,
        lstm_model,
        scaler,
        rf_model
    )

    # ========================================================
    # 2. SLOW LEAK / WARNING
    # ========================================================

    slow_results = run_scenario(
        "SLOW LEAK / WARNING",
        generate_leak(
            rate=0.10
        ),
        if_model,
        lstm_model,
        scaler,
        rf_model
    )

    # ========================================================
    # 3. MEDIUM LEAK / PREDICTIVE
    # ========================================================

    medium_results = run_scenario(
        "MEDIUM LEAK / PREDICTIVE",
        generate_leak(
            rate=0.30
        ),
        if_model,
        lstm_model,
        scaler,
        rf_model
    )

    # ========================================================
    # 4. FAST LEAK / CRITICAL
    # ========================================================

    critical_results = run_scenario(
        "FAST LEAK / CRITICAL",
        generate_leak(
            rate=0.60
        ),
        if_model,
        lstm_model,
        scaler,
        rf_model
    )

    # ========================================================
    # 5. INSUFFICIENT HISTORY
    # ========================================================

    test_insufficient_history(
        if_model,
        lstm_model,
        scaler,
        rf_model
    )

    # ========================================================
    # FINAL
    # ========================================================

    print("\n")
    print("=" * 80)
    print("ALL END-TO-END SCENARIOS COMPLETED")
    print("=" * 80)


if __name__ == "__main__":
    main()