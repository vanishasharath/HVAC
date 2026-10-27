"""
TFLite Edge Model - On-Device Anomaly Detection
=================================================
Trains a SMALL, fast neural network (not the cloud Isolation Forest/LSTM -
those can't run on an ESP32) that classifies a single sensor reading as
healthy or anomalous. Converts it to TFLite with int8 quantization so it
fits in the ESP32's limited flash/RAM.

This is deliberately simpler than the cloud pipeline - it trades some
accuracy for the ability to run locally with no internet connection,
exactly as described in your report's edge computing layer.
"""

import numpy as np
import pandas as pd
import tensorflow as tf
from tensorflow.keras import layers, models
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import MinMaxScaler
from sklearn.metrics import classification_report
import joblib
import os

DATA_PATH = "data/r32_synthetic_full.csv"
KERAS_MODEL_OUT = "models/edge_anomaly_model.h5"
TFLITE_MODEL_OUT = "models/edge_anomaly_model.tflite"
TFLITE_QUANTIZED_OUT = "models/edge_anomaly_model_quantized.tflite"
SCALER_OUT = "models/edge_scaler.pkl"

# Deliberately using ONLY the 5 raw sensor readings (no rolling stats,
# no rate-of-change) - the ESP32 firmware computes this per-sample without
# needing to maintain rolling window state, keeping the edge logic simple.
FEATURE_COLS = ["gas_ppm", "pressure", "temperature", "humidity", "compressor_current"]


def build_edge_model(n_features):
    """
    Intentionally tiny: 2 dense layers, ~1-2K parameters total.
    This needs to fit in KBs of flash on an ESP32, not MBs.
    """
    model = models.Sequential([
        layers.Input(shape=(n_features,)),
        layers.Dense(16, activation="relu"),
        layers.Dense(8, activation="relu"),
        layers.Dense(1, activation="sigmoid"),  # binary: healthy (0) vs anomalous (1)
    ])
    model.compile(optimizer="adam", loss="binary_crossentropy", metrics=["accuracy"])
    return model


def train_edge_model():
    df = pd.read_csv(DATA_PATH)

    scaler = MinMaxScaler()
    X = scaler.fit_transform(df[FEATURE_COLS])
    y = df["label"].values

    # Split by sequence to avoid leakage, same reasoning as LSTM/RF
    seq_ids = df["sequence_id"].unique()
    train_ids, test_ids = train_test_split(seq_ids, test_size=0.2, random_state=42)
    train_mask = df["sequence_id"].isin(train_ids).values
    test_mask = df["sequence_id"].isin(test_ids).values

    X_train, y_train = X[train_mask], y[train_mask]
    X_test, y_test = X[test_mask], y[test_mask]

    print(f"Train: {len(X_train)} rows | Test: {len(X_test)} rows")

    model = build_edge_model(n_features=X.shape[1])
    model.summary()

    model.fit(
        X_train, y_train,
        validation_data=(X_test, y_test),
        epochs=20,
        batch_size=128,
        callbacks=[tf.keras.callbacks.EarlyStopping(monitor="val_loss", patience=3, restore_best_weights=True)],
        verbose=2,
    )

    y_pred = (model.predict(X_test, verbose=0) > 0.5).astype(int).flatten()
    print("\n--- Edge Model Evaluation (float32, pre-quantization) ---")
    print(classification_report(y_test, y_pred, target_names=["healthy", "anomaly"]))

    os.makedirs("models", exist_ok=True)
    model.save(KERAS_MODEL_OUT)
    joblib.dump(scaler, SCALER_OUT)

    return model, scaler, X_train, X_test, y_test


def convert_to_tflite(model, X_train):
    """
    Two conversions:
      1. Plain float32 TFLite - smaller than Keras .h5 but not fully optimized
      2. Int8-quantized TFLite - much smaller, what actually goes on the ESP32

    Quantization needs a "representative dataset" (a sample of real training
    data) so the converter knows what range of values to expect and can pick
    good int8 scaling factors.
    """
    # --- Plain float32 conversion ---
    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    tflite_float = converter.convert()
    with open(TFLITE_MODEL_OUT, "wb") as f:
        f.write(tflite_float)

    # --- Int8 quantized conversion ---
    # IMPORTANT: the representative dataset must include a MIX of healthy and
    # anomalous examples. If it only sees one class (e.g. the first 200 rows,
    # which are sequentially ordered and mostly healthy), the converter
    # calibrates its int8 ranges too narrowly around "normal" outputs, and
    # anomaly predictions get clipped/collapsed to a single wrong value.
    rng = np.random.RandomState(42)
    shuffled_idx = rng.permutation(len(X_train))[:300]

    def representative_dataset():
        for i in shuffled_idx:
            yield [X_train[i:i+1].astype(np.float32)]

    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    converter.representative_dataset = representative_dataset
    converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    converter.inference_input_type = tf.int8
    converter.inference_output_type = tf.int8
    tflite_quantized = converter.convert()
    with open(TFLITE_QUANTIZED_OUT, "wb") as f:
        f.write(tflite_quantized)

    float_size = os.path.getsize(TFLITE_MODEL_OUT)
    quant_size = os.path.getsize(TFLITE_QUANTIZED_OUT)
    print(f"\nFloat32 TFLite size: {float_size / 1024:.1f} KB")
    print(f"Int8 quantized size: {quant_size / 1024:.1f} KB")
    print(f"Size reduction: {(1 - quant_size/float_size) * 100:.1f}%")

    return tflite_quantized


def evaluate_quantized_model(X_test, y_test, scaler):
    """
    Quantization can hurt accuracy - this checks how much, so you can
    report the real edge-vs-cloud accuracy trade-off honestly.
    """
    interpreter = tf.lite.Interpreter(model_path=TFLITE_QUANTIZED_OUT)
    interpreter.allocate_tensors()
    input_details = interpreter.get_input_details()[0]
    output_details = interpreter.get_output_details()[0]

    in_scale, in_zero_point = input_details["quantization"]
    out_scale, out_zero_point = output_details["quantization"]

    preds = []
    for row in X_test:
        # Manually quantize input to int8 (mirrors what the ESP32 firmware does).
        # IMPORTANT: must clip to the valid int8 range [-128, 127] before casting -
        # values outside that range silently wrap around (e.g. 130 becomes -126)
        # instead of raising an error, which corrupts predictions without any
        # visible sign something went wrong.
        q_row = np.round(row / in_scale + in_zero_point)
        q_row = np.clip(q_row, -128, 127).astype(np.int8)
        interpreter.set_tensor(input_details["index"], q_row.reshape(1, -1))
        interpreter.invoke()
        q_out = interpreter.get_tensor(output_details["index"])
        # Dequantize output back to a float probability
        prob = (q_out.astype(np.float32) - out_zero_point) * out_scale
        preds.append(1 if prob[0][0] > 0.5 else 0)

    print("\n--- Edge Model Evaluation (INT8 quantized, what actually runs on ESP32) ---")
    print(classification_report(y_test, preds, target_names=["healthy", "anomaly"]))


if __name__ == "__main__":
    model, scaler, X_train, X_test, y_test = train_edge_model()
    convert_to_tflite(model, X_train)
    evaluate_quantized_model(X_test, y_test, scaler)
    print(f"\nDone. Deployable model: {TFLITE_QUANTIZED_OUT}")
    print(f"Scaler (needed to preprocess ESP32 sensor readings identically): {SCALER_OUT}")