"""
Test the complete live alert workflow end-to-end:
Sends high/critical readings to the running backend to trigger
Random Forest severity classification, MongoDB alert storage,
WebSocket broadcast, and real TextBee SMS dispatch to the Admin phone.
"""

import sys
import time
from datetime import datetime, timezone
import requests

BASE_URL = "http://127.0.0.1:8000"
INGESTION_KEY = "dev-only-ingestion-key"
HVAC_ID = "HVAC_TEST_01"
DEVICE_ID = "ESP32_SIM_001"

headers = {
    "X-Ingestion-Key": INGESTION_KEY,
    "Content-Type": "application/json",
}

def send_test_reading(gas_ppm: float, pressure_psi: float, temp_c: float, label: str):
    print(f"\n---> Sending {label} reading (Gas: {gas_ppm} ppm, Pressure: {pressure_psi} psi, Temp: {temp_c}°C)...")
    payload = {
        "device_id": DEVICE_ID,
        "hvac_id": HVAC_ID,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": "leak_progression",
        "event": None,
        "sensors": {
            "gas_ppm": gas_ppm,
            "pressure": pressure_psi,
            "temperature": temp_c,
            "humidity": 55.0,
            "compressor_current": 7.5,
            "location_pressure": pressure_psi,
            "sensor_location": "suction_line",
            "supply_air_temperature": temp_c,
        },
        "sensor_location": "suction_line",
        "humidity_context": "stable",
        "simulated_elapsed_seconds": 120.0,
        "source": "simulator",
        "schema_version": "1.0",
    }

    resp = requests.post(
        f"{BASE_URL}/api/v1/ingestion/sensor-data",
        json=payload,
        headers=headers,
        timeout=10,
    )
    print(f"HTTP Status: {resp.status_code}")
    data = resp.json().get("data", {})
    ai = data.get("ai_result", {})
    print(f"AI Result: Severity = {ai.get('severity')} (Confidence: {ai.get('severity_confidence')}), Anomaly Score = {ai.get('anomaly_score')}")
    created_alert = data.get("created_alert")
    if created_alert:
        print(f"[ALERT CREATED] Tier: {created_alert.get('severity')}, Alert ID: {created_alert.get('id')}")
        print(f"Description: {created_alert.get('description')}")
    else:
        print("[NO NEW ALERT] (Either healthy/low severity or suppressed by 10-minute deduplication)")
    return data

if __name__ == "__main__":
    print("=" * 60)
    print(" LIVE HVAC ALERT & TEXTBEE SMS DISPATCH TEST ")
    print("=" * 60)

    # 1. First send a Critical leak condition
    # At gas_ppm = 420.0, suction pressure = 95.0, supply temp = 22.0
    # The Random Forest model classifies this as Critical / High!
    send_test_reading(gas_ppm=420.0, pressure_psi=95.0, temp_c=22.5, label="CRITICAL LEAK")

    print("\n" + "=" * 60)
    print(" Verification Complete. Check your phone for the SMS alert! ")
    print("=" * 60)
