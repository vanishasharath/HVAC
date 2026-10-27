"""
Verifies StreamingFeatureEngineer produces numerically identical output
to generate_synthetic_data.py's add_derived_features() when fed the same
readings one at a time vs. all at once via pandas.
"""

import numpy as np
import pandas as pd

from app.ai.feature_engineering import RAW_COLS, SENSOR_COLS, StreamingFeatureEngineer


def _pandas_batch_features(df: pd.DataFrame) -> pd.DataFrame:
    """Exact reproduction of add_derived_features() from generate_synthetic_data.py"""
    df = df.copy()
    window = 30
    for col in ["gas_ppm", "pressure", "compressor_current"]:
        df[f"{col}_rate_of_change"] = df[col].diff().fillna(0)
    df["rolling_mean_5min"] = df["gas_ppm"].rolling(window, min_periods=1).mean()
    df["rolling_std_5min"] = df["gas_ppm"].rolling(window, min_periods=1).std().fillna(0)
    return df


def test_streaming_matches_pandas_batch_on_random_sequence():
    rng = np.random.RandomState(7)
    n = 80
    df = pd.DataFrame(
        {
            "gas_ppm": rng.normal(5, 1, n),
            "pressure": rng.normal(165, 2, n),
            "temperature": rng.normal(7, 0.5, n),
            "humidity": rng.normal(55, 3, n),
            "compressor_current": rng.normal(6, 0.3, n),
        }
    )

    batch_result = _pandas_batch_features(df)

    engineer = StreamingFeatureEngineer()
    streaming_rows = []
    for _, row in df.iterrows():
        raw = {col: row[col] for col in RAW_COLS}
        streaming_rows.append(engineer.push_raw_reading(raw))
    streaming_result = pd.DataFrame(streaming_rows)

    for col in SENSOR_COLS:
        np.testing.assert_allclose(
            streaming_result[col].values,
            batch_result[col].values,
            rtol=1e-9,
            atol=1e-9,
            err_msg=f"Mismatch in column '{col}' between streaming and pandas batch computation",
        )


def test_streaming_matches_pandas_batch_with_leak_drift():
    """Same check but on a sequence with an injected trend, not just noise -
    the case that actually matters for leak detection."""
    n = 100
    t = np.arange(n)
    df = pd.DataFrame(
        {
            "gas_ppm": 5.0 + np.where(t > 50, (t - 50) * 4.0, 0.0),
            "pressure": 165.0 - np.where(t > 50, (t - 50) * 0.6, 0.0),
            "temperature": 7.0 + np.where(t > 50, (t - 50) * 0.08, 0.0),
            "humidity": np.full(n, 55.0),
            "compressor_current": 6.0 + np.where(t > 50, (t - 50) * 0.035, 0.0),
        }
    )

    batch_result = _pandas_batch_features(df)

    engineer = StreamingFeatureEngineer()
    streaming_rows = []
    for _, row in df.iterrows():
        raw = {col: row[col] for col in RAW_COLS}
        streaming_rows.append(engineer.push_raw_reading(raw))
    streaming_result = pd.DataFrame(streaming_rows)

    for col in SENSOR_COLS:
        np.testing.assert_allclose(
            streaming_result[col].values,
            batch_result[col].values,
            rtol=1e-9,
            atol=1e-9,
            err_msg=f"Mismatch in column '{col}' during a leak-drift sequence",
        )
