"""
Live Sensor Simulator - AI-Driven HVAC Refrigerant Leak Detection
==================================================================
Simulates live sensor telemetry for an R-32 Split AC unit with:
  1. Progressively increasing refrigerant gas concentration (ppm).
  2. Location-dependent pressure dynamics (suction line, discharge line,
     liquid line, or indoor ambient plenum).
  3. Gradual supply-air temperature rise (cooling capacity failure).
  4. Contextual humidity variable (independent environmental context,
     not forced to artificially correlate with leak progression).
  5. Live AI-driven trend analysis and estimated elapsed time to defined
     simulated critical conditions.

Defined Simulated Critical Conditions:
  - Critical Refrigerant Concentration: >= 400.0 ppm
  - Critical Supply-Air Temperature:   >= 22.0 deg C (total cooling failure)
  - Critical Suction Pressure:        <= 105.0 psi (suction starvation)
  - AI Classifier Severity:           Random Forest = 'Critical'

Usage:
  python scripts/simulate_sensor_data.py
  python scripts/simulate_sensor_data.py --location suction_line --humidity fluctuating --leak-rate medium
  python scripts/simulate_sensor_data.py --location discharge_line --humidity humid --leak-rate fast
"""

import argparse
import math
import random
import sys
import time
from datetime import datetime, timezone
from typing import Dict, Tuple

import requests

BASE_URL = "http://127.0.0.1:8000"
INGESTION_API_KEY = "dev-only-ingestion-key"
DEFAULT_HVAC_ID = "HVAC_TEST_01"
DEFAULT_DEVICE_ID = "ESP32_SIM_001"

# Nominal R-32 baseline operating conditions (healthy split AC, cooling mode)
BASELINE = {
    "gas_ppm": 5.0,              # ambient background refrigerant
    "pressure_suction": 165.0,   # psi, low side (evaporator outlet)
    "pressure_discharge": 395.0, # psi, high side (compressor discharge)
    "pressure_liquid": 375.0,    # psi, liquid line (condenser outlet)
    "pressure_ambient": 14.7,    # psi (101.3 kPa), indoor duct/plenum atmospheric
    "temperature": 7.0,          # deg C, supply-air / evaporator leaving air
    "humidity_stable": 55.0,     # % RH, contextual ambient baseline
    "humidity_humid": 75.0,      # % RH, humid monsoon/coastal context
    "humidity_dry": 35.0,        # % RH, dry/winter context
    "compressor_current": 6.0,   # Amps, compressor current
}

# Sensor locations and their thermodynamic operating characteristics
SENSOR_LOCATIONS = {
    "suction_line": {
        "display": "Suction Line (Low-Side / Evap Outlet)",
        "baseline_psi": BASELINE["pressure_suction"],
        "unit": "psi",
    },
    "discharge_line": {
        "display": "Discharge Line (High-Side / Compressor Outlet)",
        "baseline_psi": BASELINE["pressure_discharge"],
        "unit": "psi",
    },
    "liquid_line": {
        "display": "Liquid Line (High-Side / Condenser Outlet)",
        "baseline_psi": BASELINE["pressure_liquid"],
        "unit": "psi",
    },
    "indoor_ambient_plenum": {
        "display": "Indoor Supply Duct / Ambient Plenum",
        "baseline_psi": BASELINE["pressure_ambient"],
        "unit": "psi",
    },
}

# Critical condition definitions
CRITICAL_LIMITS = {
    "gas_ppm": 400.0,
    "temperature": 22.0,
    "pressure_suction": 105.0,
}


class LiveLeakSimulator:
    """
    Generates realistic, physics-grounded time-series telemetry for
    live HVAC monitoring and AI trend evaluation.
    """

    def __init__(
        self,
        sensor_location: str = "suction_line",
        humidity_context: str = "stable",
        leak_rate: str = "medium",
        hvac_id: str = DEFAULT_HVAC_ID,
        device_id: str = DEFAULT_DEVICE_ID,
        base_url: str = BASE_URL,
        api_key: str = INGESTION_API_KEY,
    ):
        if sensor_location not in SENSOR_LOCATIONS:
            sensor_location = "suction_line"

        self.sensor_location = sensor_location
        self.humidity_context = humidity_context
        self.leak_rate = leak_rate
        self.hvac_id = hvac_id
        self.device_id = device_id
        self.base_url = base_url.rstrip("/")
        self.headers = {"Content-Type": "application/json", "x-api-key": api_key}

        # Rate multipliers calibrated for realistic slow leak progressions:
        # ultra_slow: ~200 steps to critical (~50 hours of HVAC runtime)
        # slow: ~125 steps to critical (~31.2 hours of HVAC runtime - realistic pinhole micro-leak)
        # medium: ~50 steps to critical (~12.5 hours)
        # fast: ~23 steps to critical (~5.75 hours)
        rate_map = {"ultra_slow": 0.005, "slow": 0.008, "medium": 0.020, "fast": 0.045}
        self.k_rate = rate_map.get(leak_rate, 0.008)

        # Environmental random walk state
        self._humidity_walk = self._get_initial_humidity()
        self._leak_start_time = None
        self._step_index = 0

    def _get_initial_humidity(self) -> float:
        if self.humidity_context == "humid":
            return BASELINE["humidity_humid"]
        elif self.humidity_context == "dry":
            return BASELINE["humidity_dry"]
        else:
            return BASELINE["humidity_stable"]

    def _generate_humidity(self, step: int) -> float:
        """
        Humidity is a purely contextual variable. It does NOT force-increase
        or force-decrease with the leak. It reflects the environment.
        """
        base = self._get_initial_humidity()

        if self.humidity_context == "stable":
            # Stable ambient room humidity with slight sensor jitter
            return round(base + random.gauss(0, 0.6), 1)

        elif self.humidity_context == "humid":
            # High humidity coastal/rainy weather context
            return round(base + random.gauss(0, 0.8), 1)

        elif self.humidity_context == "dry":
            # Low humidity winter/arid context
            return round(base + random.gauss(0, 0.5), 1)

        elif self.humidity_context == "fluctuating":
            # Diurnal ambient swing (cyclic weather independent of leak)
            cycle = math.sin(step * 0.15) * 4.5
            return round(base + cycle + random.gauss(0, 0.4), 1)

        elif self.humidity_context == "random_walk":
            # Stochastic environmental walk bounded between 40% and 70%
            self._humidity_walk += random.gauss(0, 0.4)
            self._humidity_walk = max(40.0, min(70.0, self._humidity_walk))
            return round(self._humidity_walk, 1)

        return round(base, 1)

    def healthy_reading(self, step: int = 0) -> Tuple[dict, dict]:
        """
        Generates healthy normal baseline readings.
        Returns: (ai_sensors_dict, raw_display_dict)
        """
        duty = math.sin(step / 6.0) * 0.4

        gas_ppm = max(1.0, BASELINE["gas_ppm"] + random.gauss(0, 0.4))
        supply_temp = BASELINE["temperature"] + duty * 0.5 + random.gauss(0, 0.25)
        humidity = self._generate_humidity(step)
        current = BASELINE["compressor_current"] + duty * 0.3 + random.gauss(0, 0.15)

        # Baseline pressure depends on sensor location
        loc_info = SENSOR_LOCATIONS[self.sensor_location]
        base_press = loc_info["baseline_psi"]

        if self.sensor_location == "suction_line":
            physical_press = base_press + duty * 1.5 + random.gauss(0, 0.8)
            ai_press = physical_press
        elif self.sensor_location == "discharge_line":
            physical_press = base_press + duty * 3.0 + random.gauss(0, 1.5)
            # Normal baseline suction equivalent for AI model feature vector
            ai_press = BASELINE["pressure_suction"] + duty * 1.5 + random.gauss(0, 0.8)
        elif self.sensor_location == "liquid_line":
            physical_press = base_press + duty * 2.5 + random.gauss(0, 1.2)
            ai_press = BASELINE["pressure_suction"] + duty * 1.5 + random.gauss(0, 0.8)
        else:  # indoor_ambient_plenum
            physical_press = base_press + random.gauss(0, 0.05)  # atmospheric ~14.7 psi
            ai_press = BASELINE["pressure_suction"] + duty * 1.5 + random.gauss(0, 0.8)

        sensors = {
            "gas_ppm": round(gas_ppm, 2),
            "pressure": round(ai_press, 2),
            "temperature": round(supply_temp, 2),
            "humidity": round(humidity, 1),
            "compressor_current": round(current, 2),
            "location_pressure": round(physical_press, 2),
            "sensor_location": self.sensor_location,
            "supply_air_temperature": round(supply_temp, 2),
        }

        meta = {
            "location_pressure": round(physical_press, 2),
            "location_unit": loc_info["unit"],
            "location_name": loc_info["display"],
            "progress_pct": 0.0,
        }

        return sensors, meta

    def drifting_reading(self, step: int) -> Tuple[dict, dict]:
        """
        Generates progressively drifting readings reflecting:
          - Progressively increasing gas concentration (ppm).
          - Pressure behavior based on sensor's physical location.
          - Gradual supply-air temperature rise.
          - Independent contextual humidity.
        """
        progress = min(step * self.k_rate, 1.0)
        duty = math.sin(step / 6.0) * 0.4

        # 1. Progressively increasing gas concentration
        # Accelerates smoothly as leak expands, up to ~430 ppm at full leak
        gas_noise = random.gauss(0, 1.2)
        gas_ppm = BASELINE["gas_ppm"] + (progress ** 1.1) * 420.0 + gas_noise
        gas_ppm = max(BASELINE["gas_ppm"], round(gas_ppm, 2))

        # 2. Gradual supply-air temperature rise (loss of cooling)
        # Normal 7°C supply air climbs up to 23.5°C as evaporator starves
        temp_noise = random.gauss(0, 0.3)
        supply_temp = BASELINE["temperature"] + progress * 16.5 + temp_noise
        supply_temp = round(supply_temp, 2)

        # 3. Contextual humidity (independent environmental variable)
        humidity = self._generate_humidity(step)

        # 4. Compressor current climbs as compressor labors under high superheat
        current_noise = random.gauss(0, 0.15)
        current = BASELINE["compressor_current"] + progress * 3.5 + current_noise
        current = round(current, 2)

        # 5. Pressure behavior based on the sensor's physical location
        loc_info = SENSOR_LOCATIONS[self.sensor_location]
        base_press = loc_info["baseline_psi"]

        if self.sensor_location == "suction_line":
            # Suction line drops monotonically from 165 down towards ~102 psi
            press_drop = progress * 62.0
            physical_press = base_press - press_drop + random.gauss(0, 0.8)
            ai_press = physical_press

        elif self.sensor_location == "discharge_line":
            # High-side head pressure: early slight surge (+15 psi) due to high
            # superheat and compressor strain, followed by steep decline as charge empties
            if progress < 0.25:
                delta_p = (progress / 0.25) * 18.0
            else:
                delta_p = 18.0 - ((progress - 0.25) / 0.75) * 115.0
            physical_press = base_press + delta_p + random.gauss(0, 2.0)
            # Cycle low-side equivalent for AI feature model
            ai_press = BASELINE["pressure_suction"] - (progress * 62.0) + random.gauss(0, 0.8)

        elif self.sensor_location == "liquid_line":
            # Loss of subcooling causes vapor bubbles and flutter, dropping from 375 to ~285 psi
            liquid_drop = progress * 90.0 + math.sin(step * 0.8) * 3.5
            physical_press = base_press - liquid_drop + random.gauss(0, 1.5)
            ai_press = BASELINE["pressure_suction"] - (progress * 62.0) + random.gauss(0, 0.8)

        else:  # indoor_ambient_plenum
            # Plenum air stays atmospheric (~14.7 psi / 101.3 kPa) despite refrigerant leak!
            physical_press = base_press + random.gauss(0, 0.08)
            ai_press = BASELINE["pressure_suction"] - (progress * 62.0) + random.gauss(0, 0.8)

        sensors = {
            "gas_ppm": gas_ppm,
            "pressure": round(ai_press, 2),
            "temperature": supply_temp,
            "humidity": humidity,
            "compressor_current": current,
            "location_pressure": round(physical_press, 2),
            "sensor_location": self.sensor_location,
            "supply_air_temperature": supply_temp,
        }

        meta = {
            "location_pressure": round(physical_press, 2),
            "location_unit": loc_info["unit"],
            "location_name": loc_info["display"],
            "progress_pct": round(progress * 100.0, 1),
        }

        return sensors, meta

    def send_reading(
        self,
        sensors: dict,
        meta: dict,
        mode: str = "normal",
        event: str = None,
        elapsed_sec: float = 0.0,
        is_repair: bool = False,
    ) -> dict:
        """
        Sends payload to the backend and returns the parsed server response.
        """
        payload = {
            "device_id": self.device_id,
            "hvac_id": self.hvac_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mode": mode,
            "event": event,
            "sensors": sensors,
            "sensor_location": self.sensor_location,
            "humidity_context": self.humidity_context,
            "simulated_elapsed_seconds": elapsed_sec,
            "simulated_operating_seconds": elapsed_sec,
            "is_repair": is_repair or (event == "repaired"),
            "edge_anomaly_score": None,
            "source": "simulator",
            "schema_version": "1.0",
        }

        resp_data = {}
        http_code = 0
        try:
            response = requests.post(
                f"{self.base_url}/api/v1/ingestion/sensor-data",
                json=payload,
                headers=self.headers,
                timeout=6,
            )
            http_code = response.status_code
            resp_data = response.json()
        except requests.exceptions.RequestException as exc:
            return {"error": str(exc), "http_code": http_code}

        ai = resp_data.get("data", {}).get("ai_result") or {}
        crit_est = (
            ai.get("critical_estimation")
            or resp_data.get("data", {}).get("critical_estimation")
            or {}
        )

        return {
            "http_code": http_code,
            "ai": ai,
            "critical_estimation": crit_est,
            "payload": payload,
        }


def format_progress_bar(pct: float, width: int = 20) -> str:
    filled = int(width * (min(100.0, max(0.0, pct)) / 100.0))
    bar = "=" * filled + (">" if filled < width else "") + " " * (width - filled - (1 if filled < width else 0))
    return f"[{bar}] {pct:5.1f}%"


def run_live_simulation(
    location: str = "suction_line",
    humidity: str = "stable",
    leak_rate: str = "slow",
    normal_steps: int = 3,
    leak_steps: int = 60,
    delay: float = 1.0,
    hvac_id: str = DEFAULT_HVAC_ID,
    base_url: str = BASE_URL,
    repair_step: int = 0,
):
    simulator = LiveLeakSimulator(
        sensor_location=location,
        humidity_context=humidity,
        leak_rate=leak_rate,
        hvac_id=hvac_id,
        base_url=base_url,
    )

    print("\n" + "=" * 80)
    print("  AI-POWERED LIVE HVAC SLOW-LEAK SIMULATOR (HOURS-BASED ETTC)")
    print("=" * 80)
    print(f"  HVAC Unit:         {hvac_id}")
    print(f"  Sensor Location:   {SENSOR_LOCATIONS.get(location, {}).get('display', location)}")
    print(f"  Humidity Context:  {humidity.upper()} (Contextual variable, decoupled from leak)")
    print(f"  Leak Rate:         {leak_rate.upper()} (Slow pinhole progression, ~18-24h to critical)")
    print(f"  Time Scale:        1 demo step = 15 min HVAC operating time (4 steps = 1 hour)")
    if repair_step > 0:
        print(f"  Repair Scheduled:  Step {repair_step} (Simulating maintenance fix before critical)")
    print(f"  Target Endpoint:   {base_url}/api/v1/ingestion/sensor-data")
    print("-" * 80)
    print("  Simulated Defined Critical Conditions:")
    print("    * Refrigerant Gas >= 400.0 ppm")
    print("    * Supply-Air Temp >= 22.0 °C (loss of cooling capacity)")
    print("    * Suction Pressure <= 105.0 psi (compressor starvation)")
    print("    * AI Model Severity = 'Critical'")
    print("=" * 80 + "\n")

    # Phase 1: Healthy Baseline
    print(">>> PHASE 1: HEALTHY BASELINE OPERATION <<<")
    for i in range(1, normal_steps + 1):
        sensors, meta = simulator.healthy_reading(step=i)
        res = simulator.send_reading(sensors, meta, mode="normal", event="baseline", elapsed_sec=0.0)

        if "error" in res:
            print(f"  [Step {i:02d}] Connection Error: {res['error']}")
            print("  Make sure the FastAPI backend is running: uvicorn app.main:app --reload")
            return

        ai = res.get("ai", {})
        crit = res.get("critical_estimation", {})
        rf_sev = ai.get("severity", "Low")
        ettc_str = crit.get("time_to_critical_formatted", "> 24 Hours (Normal Operation)")

        print(
            f"  [Baseline {i:02d}] "
            f"Gas={sensors['gas_ppm']:5.1f} ppm | "
            f"SupplyTemp={sensors['temperature']:4.1f}°C | "
            f"Press({location})={meta['location_pressure']:5.1f} psi | "
            f"RH={sensors['humidity']:4.1f}% | "
            f"AI_Sev={rf_sev:8s} | ETTC: {ettc_str}"
        )
        time.sleep(delay)

    # Phase 2: Active Leak Sequence
    print("\n>>> PHASE 2: SLOW LEAK INJECTION & AI TREND PROJECTION IN HOURS <<<")
    start_wall_time = time.time()

    for step in range(1, leak_steps + 1):
        # Check if user requested a simulated repair at this step
        if repair_step > 0 and step == repair_step:
            print(f"\n  [🔧 STEP {step:02d}: TECHNICIAN MAINTENANCE PERFORMED]")
            print("  Technician repaired micro-fracture and recharged R-32 refrigerant.")
            sensors, meta = simulator.healthy_reading(step=0)
            res = simulator.send_reading(sensors, meta, mode="normal", event="repaired", elapsed_sec=0.0, is_repair=True)
            crit = res.get("critical_estimation", {})
            ettc_str = crit.get("time_to_critical_formatted", "> 24 Hours (System Repaired & Nominal)")
            print(f"  Status: HEALTHY_STABLE | ETTC: {ettc_str} [✓ Repaired before critical condition!]\n")
            time.sleep(delay * 2)
            break

        # 1 step = 15 minutes = 900 seconds of operating time
        elapsed_operating_sec = step * 900.0
        elapsed_operating_hours = elapsed_operating_sec / 3600.0

        sensors, meta = simulator.drifting_reading(step=step)
        event_name = "drifting"
        if step == 1:
            event_name = "leak_started"
        elif meta["progress_pct"] >= 100.0:
            event_name = "critical_reached"

        res = simulator.send_reading(
            sensors,
            meta,
            mode="demo",
            event=event_name,
            elapsed_sec=elapsed_operating_sec,
        )

        if "error" in res:
            print(f"  [Step {step:02d}] Connection Error: {res['error']}")
            break

        ai = res.get("ai", {})
        crit = res.get("critical_estimation", {})
        rf_sev = ai.get("severity", "?")
        rf_conf = ai.get("severity_confidence", 0.0)

        ettc_str = crit.get("time_to_critical_formatted", "--")
        driver = crit.get("primary_driver_display", "Calculating...")
        progress_crit = crit.get("progress_to_critical_pct", meta["progress_pct"])
        bar = format_progress_bar(progress_crit, width=15)

        # Rate of change trends in hours
        trends = crit.get("trends", {})
        gas_rate_hr = trends.get("gas_ppm_per_hour", 0.0)
        temp_rate_hr = trends.get("temp_per_hour", 0.0)

        status_tag = ""
        if crit.get("critical_reached"):
            status_tag = " [!! CRITICAL LIMIT EXCEEDED !!]"
        elif rf_sev in ["High", "Critical"]:
            status_tag = f" [AI {rf_sev.upper()}]"

        print(
            f"  [Step {step:02d} | OpTime: {elapsed_operating_hours:4.1f}h] "
            f"Gas={sensors['gas_ppm']:5.1f} ppm (+{gas_rate_hr:4.1f}/h) | "
            f"SupplyAir={sensors['temperature']:4.1f}°C (+{temp_rate_hr:3.2f}/h) | "
            f"P={meta['location_pressure']:5.1f} psi | "
            f"RH={sensors['humidity']:4.1f}% | "
            f"AI={rf_sev} | "
            f"ETTC: {ettc_str} {bar}{status_tag}"
        )

        time.sleep(delay)

    print("\n" + "=" * 80)
    print("  SIMULATION COMPLETE")
    print(f"  Total demonstration wall time: {time.time() - start_wall_time:.1f} seconds")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="HVAC Live Slow-Leak Simulator with location-dependent pressure and AI trend estimation in hours."
    )
    parser.add_argument(
        "--location", "-l",
        choices=["suction_line", "discharge_line", "liquid_line", "indoor_ambient_plenum"],
        default="suction_line",
        help="Physical sensor location on HVAC cycle (default: suction_line)",
    )
    parser.add_argument(
        "--humidity", "-H",
        choices=["stable", "humid", "dry", "fluctuating", "random_walk"],
        default="stable",
        help="Contextual environmental humidity profile (default: stable)",
    )
    parser.add_argument(
        "--leak-rate", "-r",
        choices=["ultra_slow", "slow", "medium", "fast"],
        default="slow",
        help="Rate of leak progression (default: slow)",
    )
    parser.add_argument(
        "--steps", "-n",
        type=int,
        default=60,
        help="Number of leak steps to simulate (default: 60)",
    )
    parser.add_argument(
        "--repair-step",
        type=int,
        default=0,
        help="Step at which to simulate technician maintenance/repair (default: 0 = no repair)",
    )
    parser.add_argument(
        "--normal-count",
        type=int,
        default=3,
        help="Number of normal baseline readings before leak (default: 3)",
    )
    parser.add_argument(
        "--delay", "-d",
        type=float,
        default=1.0,
        help="Delay in seconds between sensor readings (default: 1.0)",
    )
    parser.add_argument(
        "--hvac-id",
        type=str,
        default=DEFAULT_HVAC_ID,
        help=f"Target HVAC Unit ID (default: {DEFAULT_HVAC_ID})",
    )
    parser.add_argument(
        "--url",
        type=str,
        default=BASE_URL,
        help=f"FastAPI backend base URL (default: {BASE_URL})",
    )

    args = parser.parse_args()

    run_live_simulation(
        location=args.location,
        humidity=args.humidity,
        leak_rate=args.leak_rate,
        normal_steps=args.normal_count,
        leak_steps=args.steps,
        delay=args.delay,
        hvac_id=args.hvac_id,
        base_url=args.url,
        repair_step=args.repair_step,
    )
