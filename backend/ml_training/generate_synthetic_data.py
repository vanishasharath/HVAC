"""
Synthetic Data Generator - R-32 Refrigerant Leak Detection
=============================================================
Generates time-series sensor data for a single R-32 split AC unit.
Produces two kinds of sequences:
  1. HEALTHY sequences  -> used to train Isolation Forest (unsupervised, healthy-only)
  2. LEAK sequences      -> healthy baseline + injected gradual drift, labeled by severity
                            -> used to train LSTM (forecasting) and Random Forest (classification)

Sampling rate: every 10 seconds (matches your report's spec)
"""

import numpy as np
import pandas as pd
import os

# ----------------------------
# Reproducibility
# ----------------------------
np.random.seed(42)

# ----------------------------
# R-32 baseline operating ranges (healthy split AC, 1.5-2 ton)
# ----------------------------
BASELINE = {
    "gas_ppm": 5.0,          # near-zero ambient refrigerant
    "pressure": 165.0,       # psi, suction side
    "temperature": 7.0,      # deg C, evaporator
    "humidity": 55.0,        # % ambient
    "compressor_current": 6.0,  # amps
}

# Natural noise levels (sensor + environmental jitter) during healthy operation
NOISE = {
    "gas_ppm": 0.8,
    "pressure": 2.0,
    "temperature": 0.5,
    "humidity": 3.0,
    "compressor_current": 0.3,
}

SAMPLE_INTERVAL_SEC = 10


def generate_healthy_sequence(duration_minutes=180, drift_scale=1.0):
    """
    Simulate a healthy-operation sequence with natural fluctuation
    (compressor duty cycles, ambient temp swings) but NO leak trend.
    """
    n_samples = int((duration_minutes * 60) / SAMPLE_INTERVAL_SEC)
    t = np.arange(n_samples)

    # Compressor duty-cycle behavior: slow sinusoidal variation (on/off cycling)
    duty_cycle = np.sin(t / 60.0) * 0.5

    data = {
        "gas_ppm": BASELINE["gas_ppm"] + np.random.normal(0, NOISE["gas_ppm"], n_samples),
        "pressure": BASELINE["pressure"] + duty_cycle * 3 + np.random.normal(0, NOISE["pressure"], n_samples),
        "temperature": BASELINE["temperature"] + duty_cycle * 1.5 + np.random.normal(0, NOISE["temperature"], n_samples),
        "humidity": BASELINE["humidity"] + np.random.normal(0, NOISE["humidity"], n_samples),
        "compressor_current": BASELINE["compressor_current"] + duty_cycle * 0.8 + np.random.normal(0, NOISE["compressor_current"], n_samples),
    }

    df = pd.DataFrame(data)
    df["label"] = 0        # 0 = healthy
    df["severity"] = "none"
    return df


def generate_leak_sequence(duration_minutes=180, leak_start_frac=0.3,
                            leak_rate="slow", severity="warning"):
    """
    Simulate a sequence that starts healthy, then transitions into a leak.

    leak_rate: "slow" | "medium" | "fast" -> controls how quickly drift accelerates
    severity:  "warning" | "predictive" | "critical" -> how far the drift is allowed to progress
    """
    n_samples = int((duration_minutes * 60) / SAMPLE_INTERVAL_SEC)
    t = np.arange(n_samples)
    leak_start = int(n_samples * leak_start_frac)

    duty_cycle = np.sin(t / 60.0) * 0.5

    # Base healthy signal everywhere
    gas_ppm = BASELINE["gas_ppm"] + np.random.normal(0, NOISE["gas_ppm"], n_samples)
    pressure = BASELINE["pressure"] + duty_cycle * 3 + np.random.normal(0, NOISE["pressure"], n_samples)
    temperature = BASELINE["temperature"] + duty_cycle * 1.5 + np.random.normal(0, NOISE["temperature"], n_samples)
    humidity = BASELINE["humidity"] + np.random.normal(0, NOISE["humidity"], n_samples)
    compressor_current = BASELINE["compressor_current"] + duty_cycle * 0.8 + np.random.normal(0, NOISE["compressor_current"], n_samples)

    # Drift rate constants (per sample) - tuned so "slow" leaks take longer to become obvious
    rate_map = {
        "slow": 0.008,
        "medium": 0.025,
        "fast": 0.06,
    }
    k = rate_map[leak_rate]

    # Severity caps how far the drift progresses (fraction of full leak progression)
    severity_cap = {"warning": 0.3, "predictive": 0.6, "critical": 1.0}
    cap = severity_cap[severity]

    post_leak_len = n_samples - leak_start
    progress = np.clip(np.arange(post_leak_len) * k, 0, cap)  # 0 -> cap, monotonic drift

    # Apply correlated drift: gas UP, pressure DOWN, temp UP, current UP
    gas_ppm[leak_start:] += progress * 400          # up to ~400ppm at full leak
    pressure[leak_start:] -= progress * 60           # pressure drops up to ~60 psi
    temperature[leak_start:] += progress * 8          # evaporator warms up to ~8C
    compressor_current[leak_start:] += progress * 3.5  # current climbs up to ~3.5A extra

    labels = np.zeros(n_samples, dtype=int)
    labels[leak_start:] = 1

    severities = np.array(["none"] * n_samples, dtype=object)
    severities[leak_start:] = severity

    df = pd.DataFrame({
        "gas_ppm": gas_ppm,
        "pressure": pressure,
        "temperature": temperature,
        "humidity": humidity,
        "compressor_current": compressor_current,
        "label": labels,
        "severity": severities,
    })
    return df


def add_derived_features(df):
    """
    Adds rate-of-change and rolling-window features, per your notes.
    Rolling window ~5 min = 30 samples at 10s interval.
    """
    df = df.copy()
    window = 30  # 5 minutes at 10s sampling

    for col in ["gas_ppm", "pressure", "compressor_current"]:
        df[f"{col}_rate_of_change"] = df[col].diff().fillna(0)

    df["rolling_mean_5min"] = df["gas_ppm"].rolling(window, min_periods=1).mean()
    df["rolling_std_5min"] = df["gas_ppm"].rolling(window, min_periods=1).std().fillna(0)

    return df


def build_dataset(n_healthy_sequences=40, n_leak_sequences=60, out_dir="data"):
    os.makedirs(out_dir, exist_ok=True)

    all_sequences = []
    seq_id = 0

    # --- Healthy sequences ---
    for _ in range(n_healthy_sequences):
        dur = np.random.choice([60, 120, 180, 240])
        seq = generate_healthy_sequence(duration_minutes=dur)
        seq["sequence_id"] = seq_id
        all_sequences.append(seq)
        seq_id += 1

    # --- Leak sequences (mix of rates/severities) ---
    rates = ["slow", "medium", "fast"]
    severities = ["warning", "predictive", "critical"]
    for _ in range(n_leak_sequences):
        dur = np.random.choice([120, 180, 240, 300])
        rate = np.random.choice(rates)
        sev = np.random.choice(severities)
        start_frac = np.random.uniform(0.15, 0.5)
        seq = generate_leak_sequence(duration_minutes=dur, leak_start_frac=start_frac,
                                      leak_rate=rate, severity=sev)
        seq["sequence_id"] = seq_id
        all_sequences.append(seq)
        seq_id += 1

    full_df = pd.concat(all_sequences, ignore_index=True)
    # NOTE: groupby().apply() can silently drop the grouping column in some
    # pandas versions, so we explicitly preserve sequence_id by processing
    # each group's derived features separately and re-attaching the id.
    processed = []
    for seq_id, group in full_df.groupby("sequence_id"):
        g = add_derived_features(group.drop(columns=["sequence_id"]))
        g["sequence_id"] = seq_id
        processed.append(g)
    full_df = pd.concat(processed, ignore_index=True)

    # Save full dataset
    full_path = os.path.join(out_dir, "r32_synthetic_full.csv")
    full_df.to_csv(full_path, index=False)

    # Save healthy-only subset (for Isolation Forest training)
    healthy_only = full_df[full_df["label"] == 0]
    healthy_path = os.path.join(out_dir, "r32_healthy_only.csv")
    healthy_only.to_csv(healthy_path, index=False)

    print(f"Full dataset: {len(full_df)} rows, {seq_id} sequences -> {full_path}")
    print(f"Healthy-only: {len(healthy_only)} rows -> {healthy_path}")
    print(f"Leak rows: {len(full_df[full_df['label']==1])} ({full_df['label'].mean()*100:.1f}% of total)")
    print("\nSeverity distribution (leak rows only):")
    print(full_df[full_df["label"] == 1]["severity"].value_counts())

    return full_df


if __name__ == "__main__":
    df = build_dataset(n_healthy_sequences=40, n_leak_sequences=60)
    print("\nSample rows:")
    print(df.head(10))