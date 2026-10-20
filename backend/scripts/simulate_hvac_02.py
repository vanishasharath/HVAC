"""
Development-only sensor simulator - values match the R-32 baseline your
ML teammate's generate_synthetic_data.py trained the real models on
(BASELINE dict), so the demo sequence produces realistic AI transitions
instead of arbitrary numbers the models were never trained to expect.

USAGE:
    1. Start the server: uvicorn app.main:app --reload
    2. Make sure INGESTION_API_KEY below matches your .env
    3. python scripts/simulate_sensor_data.py
"""

import time
from datetime import datetime, timezone

import requests

BASE_URL = "http://127.0.0.1:8000"
INGESTION_API_KEY = "dev-only-ingestion-key"
HVAC_ID = "HVAC_TEST_02"
DEVICE_ID = "ESP32_SIM_001"

HEADERS = {"Content-Type": "application/json", "x-api-key": INGESTION_API_KEY}

# Matches BASELINE in generate_synthetic_data.py
BASELINE = {"gas_ppm": 5.0, "pressure": 165.0, "temperature": 7.0, "humidity": 55.0, "compressor_current": 6.0}


def healthy_reading():
    return dict(BASELINE)


def drifting_reading(step: int):
    """Matches the correlated drift pattern from generate_leak_sequence():
    gas UP, pressure DOWN, temp UP, current UP."""
    progress = min(step * 0.03, 1.0)
    return {
        "gas_ppm": BASELINE["gas_ppm"] + progress * 400,
        "pressure": BASELINE["pressure"] - progress * 60,
        "temperature": BASELINE["temperature"] + progress * 8,
        "humidity": BASELINE["humidity"],
        "compressor_current": BASELINE["compressor_current"] + progress * 3.5,
    }


def send_reading(sensors: dict, mode: str = "normal", event: str = None):
    payload = {
        "device_id": DEVICE_ID, "hvac_id": HVAC_ID,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": mode, "event": event, "sensors": sensors,
        "edge_anomaly_score": None, "source": "simulator", "schema_version": "1.0",
    }
    response = requests.post(f"{BASE_URL}/api/v1/ingestion/sensor-data", json=payload, headers=HEADERS, timeout=5)
    ai = None
    try:
        ai = response.json().get("data", {}).get("ai_result", {})
    except Exception:
        pass
    severity = ai.get("severity") if ai else "?"
    print(f"[{payload['timestamp']}] mode={mode} HTTP={response.status_code} AI_severity={severity}")


def run_normal_phase(count: int = 5, delay: float = 1.0):
    print("\n--- NORMAL OPERATION ---")
    for _ in range(count):
        send_reading(healthy_reading(), mode="normal")
        time.sleep(delay)


def run_demo_leak_sequence(steps: int = 40, delay: float = 1.0):
    print("\n--- DEMO: LEAK SEQUENCE (simulated, matches real training data pattern) ---")
    send_reading(healthy_reading(), mode="demo", event="demo_started")
    time.sleep(delay)
    for step in range(1, steps + 1):
        send_reading(drifting_reading(step), mode="demo", event="drifting")
        time.sleep(delay)


if __name__ == "__main__":
    run_normal_phase(count=3, delay=1)
    run_demo_leak_sequence(steps=40, delay=1)
