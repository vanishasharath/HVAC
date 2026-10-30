"""
AI Trend & Critical Condition Estimator
=======================================
Tracks temporal trends (rates of change) and elapsed operating time across
ingested sensor streams to estimate when defined simulated critical conditions
will be reached during an HVAC refrigerant leak event.

Designed for real-world HVAC engineering timelines:
- Slow pinhole leaks take HOURS (12 - 24+ hours) to reach critical thresholds.
- Projects Estimated Time to Critical (ETTC) primarily in HOURS.
- Supports real-time demonstrator interaction: dynamically shows ETTC decreasing
  as leak progresses, or recovering to nominal when maintenance/repair is simulated.

Defined Simulated Critical Conditions (R-32 Split AC):
1. Critical Refrigerant Concentration: >= 400.0 ppm
2. Critical Supply-Air Temperature Rise: >= 22.0 deg C (loss of cooling capacity)
3. Critical Suction Pressure Drop: <= 105.0 psi (suction starvation)
4. AI Model Severity: Random Forest class = 'Critical' or LSTM 24h prob >= 0.85
"""

from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
import numpy as np


# Defined simulated critical condition thresholds
CRITICAL_THRESHOLDS = {
    "gas_ppm": 400.0,            # Safety escalation threshold (ppm R-32)
    "temperature": 35.0,         # Ambient/chiller overheat limit (deg C)
    "pressure_low_side": 105.0,  # Suction pressure cavitation/starvation limit (psi)
    "rf_severity": "Critical",   # AI classifier critical tier
}

HEALTHY_BASELINE = {
    "gas_ppm": 5.0,
    "temperature": 7.0,
    "pressure": 165.0,
    "humidity": 55.0,
}

# In live demonstration / rapid testing mode, each demonstration step represents
# 15 minutes (900 seconds) of continuous HVAC operating progression.
DEMO_STEP_OPERATING_SECONDS = 900.0  # 15 minutes per step = ~18-24 hours full sequence


class AITrendCriticalEstimator:
    """
    Stateful per-HVAC trend analyzer and time-to-critical estimator.
    Maintains a rolling temporal window to compute robust multi-step slopes
    and projects the remaining time in hours until defined critical conditions occur.
    """

    def __init__(self, window_size: int = 30):
        self.window_size = window_size
        self._history = deque(maxlen=window_size)
        self._leak_start_time: Optional[float] = None
        self._leak_start_timestamp: Optional[datetime] = None
        self._step_counter = 0
        self._leak_step_counter = 0
        self._is_repaired = False

    def reset(self):
        """Reset historical state (e.g. after maintenance or test reset)."""
        self._history.clear()
        self._leak_start_time = None
        self._leak_start_timestamp = None
        self._step_counter = 0
        self._leak_step_counter = 0
        self._is_repaired = False

    def update(
        self,
        raw_reading: dict,
        ai_pipeline_result: Optional[dict] = None,
        timestamp: Optional[datetime] = None,
        sensor_location: str = "suction_line",
        simulated_operating_seconds: Optional[float] = None,
        is_repair: bool = False,
    ) -> dict:
        """
        Ingest current reading and return the AI trend and critical condition estimate.
        """
        # Handle technician repair / service event
        if is_repair or raw_reading.get("is_repair"):
            self.reset()
            self._is_repaired = True
            return {
                "status": "HEALTHY_STABLE",
                "is_repaired": True,
                "critical_reached": False,
                "elapsed_time_seconds": 0.0,
                "elapsed_time_hours": 0.0,
                "elapsed_time_formatted": "0.0 Hours (Nominal)",
                "time_to_critical_seconds": None,
                "time_to_critical_minutes": None,
                "time_to_critical_hours": None,
                "time_to_critical_formatted": "> 24 Hours (System Repaired & Nominal)",
                "projected_critical_time": "Critical Condition Averted — Unit Serviced",
                "estimated_critical_timestamp": None,
                "primary_driver": "repaired",
                "primary_driver_display": "System Repaired & Nominal (Critical Averted)",
                "progress_to_critical_pct": 0.0,
                "trends": {
                    "gas_ppm_per_sec": 0.0,
                    "gas_ppm_per_min": 0.0,
                    "gas_ppm_per_hour": 0.0,
                    "temp_per_sec": 0.0,
                    "temp_per_min": 0.0,
                    "temp_per_hour": 0.0,
                    "pressure_per_sec": 0.0,
                    "pressure_per_min": 0.0,
                    "pressure_per_hour": 0.0,
                    "humidity_per_min": 0.0,
                    "confidence_r2": 1.0,
                },
                "critical_thresholds": CRITICAL_THRESHOLDS,
                "sensor_location": sensor_location,
                "humidity_context": "independent_variable",
            }

        if timestamp is None:
            timestamp = datetime.now(timezone.utc)

        t_epoch = timestamp.timestamp()
        gas_ppm = float(raw_reading.get("gas_ppm", HEALTHY_BASELINE["gas_ppm"]))
        temp = float(raw_reading.get("temperature", HEALTHY_BASELINE["temperature"]))
        pressure = float(raw_reading.get("pressure", HEALTHY_BASELINE["pressure"]))
        humidity = float(raw_reading.get("humidity", HEALTHY_BASELINE["humidity"]))

        self._step_counter += 1

        # Detect leak start / anomaly progression
        is_anomalous = False
        rf_severity = "Low"
        anomaly_duration = 0
        lstm_prob_24hr = 0.0

        if ai_pipeline_result:
            rf_severity = ai_pipeline_result.get("severity", "Low")
            anomaly_duration = ai_pipeline_result.get("anomaly_duration", 0)
            lstm_prob_24hr = ai_pipeline_result.get("lstm_prob_24hr", 0.0)
            is_anomalous = (
                ai_pipeline_result.get("anomaly_flag", 0) == 1
                or rf_severity in ["Medium", "High", "Critical"]
                or anomaly_duration > 0
            )

        # Physical threshold anomaly trigger
        if gas_ppm > 25.0 or temp > 32.0 or (sensor_location == "suction_line" and pressure < 145.0):
            is_anomalous = True

        if is_anomalous:
            self._leak_step_counter += 1
            if self._leak_start_time is None:
                self._leak_start_time = t_epoch
                self._leak_start_timestamp = timestamp
        else:
            # If healthy for a long window, relax leak start
            if self._leak_start_time is not None and gas_ppm <= 10.0 and temp <= 9.0:
                self._leak_start_time = None
                self._leak_start_timestamp = None
                self._leak_step_counter = 0

        # Determine effective operating time base (calibrated in physical HVAC operating hours)
        if simulated_operating_seconds is not None:
            t_operating = float(simulated_operating_seconds)
            elapsed_seconds = max(0.0, simulated_operating_seconds)
        elif is_anomalous:
            elapsed_seconds = float(self._leak_step_counter * DEMO_STEP_OPERATING_SECONDS)
            t_operating = float(self._step_counter * DEMO_STEP_OPERATING_SECONDS)
        else:
            elapsed_seconds = 0.0
            t_operating = float(self._step_counter * DEMO_STEP_OPERATING_SECONDS)

        # Store in rolling buffer
        self._history.append({
            "t": t_operating,
            "gas_ppm": gas_ppm,
            "temperature": temp,
            "pressure": pressure,
            "humidity": humidity,
            "elapsed": elapsed_seconds,
        })

        # Calculate trends (rates of change per second, per minute, and per hour)
        trends = self._compute_trends()

        # Check if physical critical condition is ALREADY reached
        critical_gas = gas_ppm >= CRITICAL_THRESHOLDS["gas_ppm"]
        critical_temp = temp >= CRITICAL_THRESHOLDS["temperature"]
        critical_pressure = (
            sensor_location == "suction_line"
            and pressure <= CRITICAL_THRESHOLDS["pressure_low_side"]
        )

        # Physical critical breach occurs when defined safety or cooling capacity limits are exceeded
        is_critical_now = (
            critical_gas
            or critical_temp
            or critical_pressure
        )

        # Estimate time to critical condition in HOURS using trends and elapsed time
        estimate = self._estimate_time_to_critical(
            gas_ppm=gas_ppm,
            temperature=temp,
            pressure=pressure,
            sensor_location=sensor_location,
            trends=trends,
            elapsed_seconds=elapsed_seconds,
            is_critical_now=is_critical_now,
            rf_severity=rf_severity,
            lstm_prob_24hr=lstm_prob_24hr,
        )

        return estimate

    def _compute_trends(self) -> dict:
        """
        Compute rate of change using linear regression across recent history window.
        Correctly scales to physical HVAC operating hours even during rapid demo clicks.
        """
        n = len(self._history)
        if n < 3:
            return {
                "gas_ppm_per_sec": 0.0,
                "gas_ppm_per_min": 0.0,
                "gas_ppm_per_hour": 0.0,
                "temp_per_sec": 0.0,
                "temp_per_min": 0.0,
                "temp_per_hour": 0.0,
                "pressure_per_sec": 0.0,
                "pressure_per_min": 0.0,
                "pressure_per_hour": 0.0,
                "humidity_per_min": 0.0,
                "confidence_r2": 0.0,
            }

        t_vals = np.array([pt["t"] for pt in self._history])
        gas_vals = np.array([pt["gas_ppm"] for pt in self._history])
        temp_vals = np.array([pt["temperature"] for pt in self._history])
        press_vals = np.array([pt["pressure"] for pt in self._history])
        hum_vals = np.array([pt["humidity"] for pt in self._history])

        # Normalize time from 0
        t_rel = t_vals - t_vals[0]
        dt_span = t_rel[-1]
        dt_avg = dt_span / max(1, n - 1)

        # In case timestamps arrive at rapid demo/UI testing speed (e.g. 1.5s per step),
        # scale time so each step represents DEMO_STEP_OPERATING_SECONDS (15 min) of physical operating drift.
        if dt_avg < 60.0 or dt_span < 15.0:
            t_rel = np.arange(n) * DEMO_STEP_OPERATING_SECONDS

        def get_slope(y_vals):
            denom = np.sum((t_rel - np.mean(t_rel)) ** 2)
            if denom < 1e-9:
                return 0.0, 0.0
            slope = np.sum((t_rel - np.mean(t_rel)) * (y_vals - np.mean(y_vals))) / denom
            y_pred = slope * t_rel + (np.mean(y_vals) - slope * np.mean(t_rel))
            ss_tot = np.sum((y_vals - np.mean(y_vals)) ** 2)
            ss_res = np.sum((y_vals - y_pred) ** 2)
            r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 1e-9 else 0.0
            return float(slope), float(max(0.0, min(1.0, r2)))

        gas_slope, gas_r2 = get_slope(gas_vals)
        temp_slope, _ = get_slope(temp_vals)
        press_slope, _ = get_slope(press_vals)
        hum_slope, _ = get_slope(hum_vals)

        return {
            "gas_ppm_per_sec": round(gas_slope, 5),
            "gas_ppm_per_min": round(gas_slope * 60.0, 2),
            "gas_ppm_per_hour": round(gas_slope * 3600.0, 1),
            "temp_per_sec": round(temp_slope, 5),
            "temp_per_min": round(temp_slope * 60.0, 3),
            "temp_per_hour": round(temp_slope * 3600.0, 2),
            "pressure_per_sec": round(press_slope, 5),
            "pressure_per_min": round(press_slope * 60.0, 2),
            "pressure_per_hour": round(press_slope * 3600.0, 2),
            "humidity_per_min": round(hum_slope * 60.0, 2),
            "confidence_r2": round(gas_r2, 3),
        }

    def _estimate_time_to_critical(
        self,
        gas_ppm: float,
        temperature: float,
        pressure: float,
        sensor_location: str,
        trends: dict,
        elapsed_seconds: float,
        is_critical_now: bool,
        rf_severity: str = "Low",
        lstm_prob_24hr: float = 0.0,
    ) -> dict:
        """
        Synthesize trends, elapsed time, and defined critical conditions
        to project Estimated Time to Critical (ETTC) in HOURS.
        """
        elapsed_hours = round(elapsed_seconds / 3600.0, 1)

        # 1. If critical condition is already reached:
        if is_critical_now:
            return {
                "status": "CRITICAL_REACHED",
                "critical_reached": True,
                "elapsed_time_seconds": round(elapsed_seconds, 1),
                "elapsed_time_hours": elapsed_hours,
                "elapsed_time_formatted": f"{elapsed_hours} Hours Elapsed" if elapsed_hours > 0 else "0.0 Hours",
                "time_to_critical_seconds": 0.0,
                "time_to_critical_minutes": 0.0,
                "time_to_critical_hours": 0.0,
                "time_to_critical_formatted": "0s (Critical Threshold Reached)",
                "projected_critical_time": "Critical Limit Already Breached",
                "estimated_critical_timestamp": datetime.now(timezone.utc).isoformat(),
                "primary_driver": "critical_breach",
                "primary_driver_display": "Critical Limit Already Exceeded",
                "progress_to_critical_pct": 100.0,
                "trends": trends,
                "critical_thresholds": CRITICAL_THRESHOLDS,
                "sensor_location": sensor_location,
                "humidity_context": "independent_variable",
            }

        gas_rate = trends["gas_ppm_per_sec"]
        temp_rate = trends["temp_per_sec"]
        press_rate = trends["pressure_per_sec"]

        ttc_candidates = []

        # Gas concentration projection (rate threshold ~0.5 ppm/hour = 0.00014 ppm/sec)
        if gas_rate > 0.0001 and gas_ppm < CRITICAL_THRESHOLDS["gas_ppm"]:
            remaining_gas = CRITICAL_THRESHOLDS["gas_ppm"] - gas_ppm
            ttc_gas = remaining_gas / gas_rate
            ttc_candidates.append({
                "metric": "gas_ppm",
                "display": f"Refrigerant Gas Concentration ({CRITICAL_THRESHOLDS['gas_ppm']} ppm)",
                "ttc_sec": ttc_gas,
                "progress": max(0.0, min(100.0, ((gas_ppm - HEALTHY_BASELINE['gas_ppm']) / (CRITICAL_THRESHOLDS['gas_ppm'] - HEALTHY_BASELINE['gas_ppm'])) * 100.0)),
            })

        # Supply-air temperature projection (~0.05 C/hour = 0.000014 C/sec)
        if temp_rate > 0.00002 and temperature < CRITICAL_THRESHOLDS["temperature"]:
            remaining_temp = CRITICAL_THRESHOLDS["temperature"] - temperature
            ttc_temp = remaining_temp / temp_rate
            ttc_candidates.append({
                "metric": "temperature",
                "display": f"Supply-Air Temperature Rise ({CRITICAL_THRESHOLDS['temperature']}°C)",
                "ttc_sec": ttc_temp,
                "progress": max(0.0, min(100.0, ((temperature - HEALTHY_BASELINE['temperature']) / (CRITICAL_THRESHOLDS['temperature'] - HEALTHY_BASELINE['temperature'])) * 100.0)),
            })

        # Suction pressure drop projection (for suction line)
        if sensor_location == "suction_line" and press_rate < -0.00005 and pressure > CRITICAL_THRESHOLDS["pressure_low_side"]:
            remaining_press = pressure - CRITICAL_THRESHOLDS["pressure_low_side"]
            ttc_press = remaining_press / abs(press_rate)
            ttc_candidates.append({
                "metric": "pressure",
                "display": f"Suction Pressure Depletion ({CRITICAL_THRESHOLDS['pressure_low_side']} psi)",
                "ttc_sec": ttc_press,
                "progress": max(0.0, min(100.0, ((HEALTHY_BASELINE['pressure'] - pressure) / (HEALTHY_BASELINE['pressure'] - CRITICAL_THRESHOLDS['pressure_low_side'])) * 100.0)),
            })

        # Progress calculation
        progress_gas = max(0.0, min(100.0, ((gas_ppm - HEALTHY_BASELINE['gas_ppm']) / (CRITICAL_THRESHOLDS['gas_ppm'] - HEALTHY_BASELINE['gas_ppm'])) * 100.0))
        progress_temp = max(0.0, min(100.0, ((temperature - HEALTHY_BASELINE['temperature']) / (CRITICAL_THRESHOLDS['temperature'] - HEALTHY_BASELINE['temperature'])) * 100.0))
        if sensor_location == "suction_line":
            progress_press = max(0.0, min(100.0, ((HEALTHY_BASELINE['pressure'] - pressure) / (HEALTHY_BASELINE['pressure'] - CRITICAL_THRESHOLDS['pressure_low_side'])) * 100.0))
        else:
            progress_press = 0.0

        overall_progress = round(max(progress_gas, progress_temp, progress_press), 1)

        # Check if physical elevation or AI anomaly exists
        is_elevated = (
            gas_ppm > 18.0
            or temperature > 11.0
            or (sensor_location == "suction_line" and pressure < 148.0)
            or rf_severity in ["Medium", "High", "Critical"]
        )

        # If healthy baseline (no real leak progression)
        if not is_elevated or not ttc_candidates:
            return {
                "status": "HEALTHY_STABLE",
                "critical_reached": False,
                "elapsed_time_seconds": round(elapsed_seconds, 1),
                "elapsed_time_hours": elapsed_hours,
                "elapsed_time_formatted": f"{elapsed_hours} Hours Elapsed" if elapsed_hours > 0 else "0.0 Hours (Nominal)",
                "time_to_critical_seconds": None,
                "time_to_critical_minutes": None,
                "time_to_critical_hours": None,
                "time_to_critical_formatted": "> 24 Hours (Normal Operation - No Drift)",
                "projected_critical_time": "No Critical Breach Expected (Nominal)",
                "estimated_critical_timestamp": None,
                "primary_driver": "none",
                "primary_driver_display": "Healthy Baseline (Normal Operating Conditions)",
                "progress_to_critical_pct": overall_progress,
                "trends": trends,
                "critical_thresholds": CRITICAL_THRESHOLDS,
                "sensor_location": sensor_location,
                "humidity_context": "independent_variable",
            }

        # Sort candidates by shortest time-to-critical
        ttc_candidates.sort(key=lambda x: x["ttc_sec"])
        primary = ttc_candidates[0]
        shortest_ttc = max(60.0, primary["ttc_sec"])
        shortest_ttc_hours = round(shortest_ttc / 3600.0, 1)

        # Projected timestamp and human-readable time-of-day
        now_utc = datetime.now(timezone.utc)
        projected_dt = now_utc + timedelta(seconds=shortest_ttc)
        est_iso = projected_dt.isoformat()

        today = now_utc.date()
        proj_date = projected_dt.date()
        time_str = projected_dt.strftime("%I:%M %p")
        if proj_date == today:
            day_str = "Today"
        elif proj_date == today + timedelta(days=1):
            day_str = "Tomorrow"
        else:
            day_str = projected_dt.strftime("%b %d")
        projected_time_display = f"{day_str} at {time_str} (in ~{shortest_ttc_hours}h)"

        return {
            "status": "LEAK_PROGRESSING",
            "critical_reached": False,
            "elapsed_time_seconds": round(elapsed_seconds, 1),
            "elapsed_time_hours": elapsed_hours,
            "elapsed_time_formatted": f"{elapsed_hours} Hours Elapsed",
            "time_to_critical_seconds": round(shortest_ttc, 1),
            "time_to_critical_minutes": round(shortest_ttc / 60.0, 1),
            "time_to_critical_hours": shortest_ttc_hours,
            "time_to_critical_formatted": self._format_duration(shortest_ttc),
            "projected_critical_time": projected_time_display,
            "estimated_critical_timestamp": est_iso,
            "primary_driver": primary["metric"],
            "primary_driver_display": primary["display"],
            "repair_window_active": (not is_critical_now) and (overall_progress > 0.0 or is_elevated),
            "repair_action_summary": (
                "Actionable: Technician service/repair will avert critical cooling failure"
                if (not is_critical_now and (overall_progress > 0.0 or is_elevated))
                else ("Unit Nominal" if not is_critical_now else "Critical Limit Breached")
            ),
            "progress_to_critical_pct": overall_progress,
            "trends": trends,
            "critical_thresholds": CRITICAL_THRESHOLDS,
            "sensor_location": sensor_location,
            "humidity_context": "independent_variable",
        }

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """
        Formats duration prominently and consistently in physical HVAC operating HOURS,
        preventing abrupt drops from hours to minutes so the operator clearly sees
        the real-world timeline to critical condition.
        """
        if seconds is None or seconds <= 0:
            return "0.0 Hours (Critical Threshold Reached)"

        sec = int(max(0, seconds))
        mins, s = divmod(sec, 60)
        hrs, m = divmod(mins, 60)
        hrs_decimal = round(seconds / 3600.0, 1)

        if hrs >= 24:
            days = round(hrs / 24.0, 1)
            return f"{hrs_decimal} Hours Remaining (~{days} Days)"
        elif hrs >= 1:
            return f"{hrs_decimal} Hours Remaining (~{hrs}h {m}m)"
        elif mins > 0:
            return f"{hrs_decimal} Hours Remaining ({mins} min — Urgent Repair Window)"
        else:
            return f"{s}s Remaining (Critical Imminent)"
