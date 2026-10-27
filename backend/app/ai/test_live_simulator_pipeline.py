"""
End-to-end integration test verifying:
1. Progressively increasing gas concentration.
2. Pressure behavior based on sensor location.
3. Gradual supply-air temperature rise.
4. Humidity as an independent contextual variable (not forced).
5. AI trend estimation and elapsed time projecting defined critical conditions.
"""

from datetime import datetime, timezone
import pytest
from app.ai.pipeline_manager import pipeline_manager
from scripts.simulate_sensor_data import LiveLeakSimulator, SENSOR_LOCATIONS, CRITICAL_LIMITS


def test_location_dependent_pressure_and_contextual_humidity():
    # 1. Test Suction Line (Low-Side): pressure must drop
    sim_suction = LiveLeakSimulator(sensor_location="suction_line", humidity_context="stable", leak_rate="medium")
    sensors_start, _ = sim_suction.drifting_reading(step=1)
    sensors_end, _ = sim_suction.drifting_reading(step=30)
    assert sensors_end["gas_ppm"] > sensors_start["gas_ppm"]
    assert sensors_end["temperature"] > sensors_start["temperature"]  # supply air warming
    assert sensors_end["location_pressure"] < sensors_start["location_pressure"]  # suction drops

    # 2. Test Indoor Plenum: duct air pressure must remain atmospheric (~14.7 psi)
    sim_plenum = LiveLeakSimulator(sensor_location="indoor_ambient_plenum", humidity_context="humid", leak_rate="fast")
    p_start, _ = sim_plenum.drifting_reading(step=1)
    p_end, _ = sim_plenum.drifting_reading(step=25)
    assert p_end["gas_ppm"] > 300.0  # gas concentration escalates
    assert abs(p_end["location_pressure"] - 14.7) < 0.5  # pressure remains atmospheric!

    # 3. Test Humidity as Contextual Variable (not forced up or down by leak)
    sim_humid = LiveLeakSimulator(sensor_location="suction_line", humidity_context="humid", leak_rate="medium")
    sim_dry = LiveLeakSimulator(sensor_location="suction_line", humidity_context="dry", leak_rate="medium")
    s_h1, _ = sim_humid.drifting_reading(step=5)
    s_h2, _ = sim_humid.drifting_reading(step=30)
    s_d1, _ = sim_dry.drifting_reading(step=5)
    s_d2, _ = sim_dry.drifting_reading(step=30)

    # In both humid and dry scenarios, humidity reflects the environmental context
    assert s_h1["humidity"] > 70.0 and s_h2["humidity"] > 70.0  # humid context
    assert s_d1["humidity"] < 40.0 and s_d2["humidity"] < 40.0  # dry context


def test_ai_pipeline_critical_estimation_progression():
    hvac_id = "HVAC_TEST_INTEGRATION"
    pipeline_manager.reset_hvac_state(hvac_id)

    sim = LiveLeakSimulator(
        sensor_location="suction_line",
        humidity_context="fluctuating",
        leak_rate="fast",
        hvac_id=hvac_id,
    )

    # Ingest 3 baseline readings
    for i in range(3):
        raw, _ = sim.healthy_reading(step=i)
        res = pipeline_manager.process_reading(hvac_id, raw, sensor_location="suction_line")
        assert "critical_estimation" in res
        assert res["critical_estimation"]["status"] == "HEALTHY_STABLE"

    # Ingest progressing leak sequence
    step_10_res = None
    last_res = None
    for step in range(1, 25):
        raw, _ = sim.drifting_reading(step=step)
        last_res = pipeline_manager.process_reading(hvac_id, raw, sensor_location="suction_line")
        if step == 10:
            step_10_res = last_res

    # At step 10: Leak is actively progressing and ETTC is calculated in hours
    crit_10 = step_10_res["critical_estimation"]
    assert crit_10["status"] == "LEAK_PROGRESSING"
    assert crit_10["time_to_critical_seconds"] is not None
    assert crit_10["time_to_critical_seconds"] > 0
    assert crit_10["time_to_critical_hours"] is not None
    assert crit_10["elapsed_time_seconds"] > 0
    assert crit_10["trends"]["gas_ppm_per_min"] > 0
    assert crit_10["trends"]["temp_per_min"] > 0
    assert crit_10["trends"]["pressure_per_min"] < 0
    assert crit_10["progress_to_critical_pct"] > 15.0
    assert "projected_critical_time" in crit_10

    # At step 24: Fast leak reaches critical threshold (gas >= 400 ppm)
    crit_end = last_res["critical_estimation"]
    assert crit_end["critical_reached"] is True
    assert crit_end["status"] == "CRITICAL_REACHED"
    assert crit_end["time_to_critical_seconds"] == 0.0

    # Test technician repair recovery
    repair_raw, _ = sim.healthy_reading(step=0)
    repair_res = pipeline_manager.process_reading(
        hvac_id, repair_raw, sensor_location="suction_line", is_repair=True
    )
    crit_repair = repair_res["critical_estimation"]
    assert crit_repair["status"] == "HEALTHY_STABLE"
    assert crit_repair["is_repaired"] is True
    assert crit_repair["critical_reached"] is False
    assert "> 24 Hours" in crit_repair["time_to_critical_formatted"]

