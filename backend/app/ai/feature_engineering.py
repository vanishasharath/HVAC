"""
Feature engineering for the real AI pipeline.

CRITICAL: this must produce numerically IDENTICAL features to what the
models were trained on, or predictions will be silently wrong even though
nothing crashes. This is a stateful, streaming re-implementation of
generate_synthetic_data.py's add_derived_features():

    for col in ["gas_ppm", "pressure", "compressor_current"]:
        df[f"{col}_rate_of_change"] = df[col].diff().fillna(0)

    df["rolling_mean_5min"] = df["gas_ppm"].rolling(window=30, min_periods=1).mean()
    df["rolling_std_5min"] = df["gas_ppm"].rolling(window=30, min_periods=1).std().fillna(0)

Two details that are easy to get wrong and would silently corrupt every
prediction if missed:
  1. rate_of_change is a RAW diff (current - previous reading), NOT
     normalized by elapsed seconds. The training data assumes a roughly
     constant 10s sampling interval; the model was never trained to
     expect a per-second rate.
  2. The rolling window is SAMPLE-COUNT based (30 samples), not time-based.
     "5min" is just the training data's label for what 30 samples-at-10s
     happens to equal - it is NOT a pandas time-based rolling window.
"""

from collections import deque
from typing import Optional

import numpy as np

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

RAW_COLS = SENSOR_COLS[:5]
DERIVED_COLS = SENSOR_COLS[5:]

ROLLING_WINDOW = 30  # samples - matches ROLLING_WINDOW in generate_synthetic_data.py / train_random_forest.py


class StreamingFeatureEngineer:
    """
    Per-HVAC-unit state for computing the 10-feature vector one raw
    reading at a time, exactly reproducing the pandas batch computation
    the models were trained on. One instance per hvac_id - state resets
    if the process restarts (see integration notes on persistence).
    """

    def __init__(self):
        self._previous_raw: Optional[dict] = None
        self._gas_ppm_window = deque(maxlen=ROLLING_WINDOW)

    def push_raw_reading(self, raw: dict) -> dict:
        """
        raw: dict with the 5 RAW_COLS keys (gas_ppm, pressure, temperature,
        humidity, compressor_current). Returns the full 10-key feature row
        (all SENSOR_COLS), ready to hand to the real pipeline.
        """
        gas_ppm = float(raw["gas_ppm"])
        pressure = float(raw["pressure"])
        temperature = float(raw["temperature"])
        humidity = float(raw["humidity"])
        compressor_current = float(raw["compressor_current"])

        if self._previous_raw is None:
            gas_roc = 0.0
            pressure_roc = 0.0
            current_roc = 0.0
        else:
            gas_roc = gas_ppm - self._previous_raw["gas_ppm"]
            pressure_roc = pressure - self._previous_raw["pressure"]
            current_roc = compressor_current - self._previous_raw["compressor_current"]

        self._gas_ppm_window.append(gas_ppm)

        if len(self._gas_ppm_window) == 1:
            rolling_mean = gas_ppm
            rolling_std = 0.0  # pandas .std() on a single point is NaN -> .fillna(0)
        else:
            arr = np.array(self._gas_ppm_window)
            rolling_mean = float(arr.mean())
            rolling_std = float(arr.std(ddof=1))  # pandas default: sample std (ddof=1)

        self._previous_raw = {
            "gas_ppm": gas_ppm,
            "pressure": pressure,
            "compressor_current": compressor_current,
        }

        return {
            "gas_ppm": gas_ppm,
            "pressure": pressure,
            "temperature": temperature,
            "humidity": humidity,
            "compressor_current": compressor_current,
            "gas_ppm_rate_of_change": gas_roc,
            "pressure_rate_of_change": pressure_roc,
            "compressor_current_rate_of_change": current_roc,
            "rolling_mean_5min": rolling_mean,
            "rolling_std_5min": rolling_std,
        }
