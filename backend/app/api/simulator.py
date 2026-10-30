"""
API endpoints for interactive simulation, location-dependent pressure testing,
contextual humidity scenarios, and technician maintenance/repair simulation.
"""

from typing import Optional
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.ai.pipeline_manager import pipeline_manager
from app.ai.trend_estimator import CRITICAL_THRESHOLDS, DEMO_STEP_OPERATING_SECONDS
from app.schemas.sensor import SensorDataIn, SensorReadings
from app.services.sensor_service import ingest_sensor_data
from scripts.simulate_sensor_data import SENSOR_LOCATIONS, LiveLeakSimulator

router = APIRouter(prefix="/api/v1/simulator", tags=["simulator"])

# Active in-memory simulator instances per HVAC
_simulators = {}


class SimulatorStepRequest(BaseModel):
    hvac_id: str = "HVAC_SIM_01"
    sensor_location: str = Field(default="suction_line")
    humidity_context: str = Field(default="stable")
    leak_rate: str = Field(default="slow")
    step: int = Field(default=1, ge=0)
    is_leak: bool = True


class SimulatorRepairRequest(BaseModel):
    hvac_id: str = "HVAC_SIM_01"
    sensor_location: str = Field(default="suction_line")
    humidity_context: str = Field(default="stable")
    technician_name: Optional[str] = "Field Technician"
    technician_email: Optional[str] = None


@router.get("/config")
def get_simulator_config():
    """
    Returns available sensor locations, contextual humidity modes,
    and defined simulated critical conditions.
    """
    return {
        "sensor_locations": [
            {
                "id": k,
                "name": v["display"],
                "baseline_psi": v["baseline_psi"],
                "unit": v["unit"],
            }
            for k, v in SENSOR_LOCATIONS.items()
        ],
        "humidity_contexts": [
            {"id": "stable", "name": "Stable Ambient (55% RH)", "description": "Independent steady indoor climate"},
            {"id": "humid", "name": "Humid Monsoon / Coastal (75% RH)", "description": "High ambient outdoor humidity"},
            {"id": "dry", "name": "Dry / Winter (35% RH)", "description": "Low ambient humidity"},
            {"id": "fluctuating", "name": "Diurnal Weather Drift", "description": "Cyclic weather variation"},
            {"id": "random_walk", "name": "Stochastic Ambient Walk", "description": "Uncorrelated environmental walk"},
        ],
        "critical_conditions": {
            "gas_ppm_threshold": CRITICAL_THRESHOLDS["gas_ppm"],
            "temperature_threshold_c": CRITICAL_THRESHOLDS["temperature"],
            "pressure_suction_threshold_psi": CRITICAL_THRESHOLDS["pressure_low_side"],
            "rf_severity_threshold": CRITICAL_THRESHOLDS["rf_severity"],
        },
    }


@router.post("/step")
async def step_simulation(req: SimulatorStepRequest):
    """
    Generate and ingest one simulated reading with specified sensor location,
    contextual humidity, and leak progress.
    Each demonstration step represents 15 minutes of simulated HVAC operation,
    producing an Estimated Time to Critical measured in realistic physical HOURS.
    """
    key = f"{req.hvac_id}_{req.sensor_location}_{req.humidity_context}_{req.leak_rate}"
    if key not in _simulators:
        _simulators[key] = LiveLeakSimulator(
            sensor_location=req.sensor_location,
            humidity_context=req.humidity_context,
            leak_rate=req.leak_rate,
            hvac_id=req.hvac_id,
        )

    sim = _simulators[key]

    # Calculate physical operating time: 15 minutes per demo step
    simulated_operating_seconds = float(req.step * DEMO_STEP_OPERATING_SECONDS)

    if req.is_leak and req.step > 0:
        sensors, meta = sim.drifting_reading(step=req.step)
        event = "leak_started" if req.step == 1 else "drifting"
        mode = "demo"
    else:
        sensors, meta = sim.healthy_reading(step=req.step)
        event = "baseline"
        mode = "normal"

    sensor_in = SensorDataIn(
        device_id=sim.device_id,
        hvac_id=req.hvac_id,
        timestamp=datetime.now(timezone.utc),
        mode=mode,
        event=event,
        sensors=SensorReadings(**sensors),
        sensor_location=req.sensor_location,
        humidity_context=req.humidity_context,
        simulated_operating_seconds=simulated_operating_seconds,
        source="simulator",
    )

    ingestion_result = await ingest_sensor_data(sensor_in)

    return {
        "step": req.step,
        "is_leak": req.is_leak,
        "simulated_operating_seconds": simulated_operating_seconds,
        "simulated_operating_hours": round(simulated_operating_seconds / 3600.0, 1),
        "sensor_location": req.sensor_location,
        "location_metadata": meta,
        "sensors": sensors,
        "ai_result": ingestion_result.get("ai_result"),
        "critical_estimation": ingestion_result.get("critical_estimation"),
    }


@router.post("/repair")
async def repair_simulation(req: SimulatorRepairRequest):
    """
    Simulates technician service / repair:
    - Seals refrigerant leak.
    - Recharges refrigerant to full healthy charge (suction 165 psi).
    - Evaporator supply-air temperature recovers to healthy cold 7.0°C.
    - Ambient gas concentration returns to baseline 5.0 ppm.
    - Resolves all active alerts.
    - Resets AI trend estimator to HEALTHY_STABLE with '> 24 Hours (System Repaired & Nominal)'.
    """
    sim = LiveLeakSimulator(
        sensor_location=req.sensor_location,
        humidity_context=req.humidity_context,
        hvac_id=req.hvac_id,
    )
    sensors, meta = sim.healthy_reading(step=0)

    tech_id = req.technician_name or req.technician_email or "Field Technician"
    sensor_in = SensorDataIn(
        device_id=sim.device_id,
        hvac_id=req.hvac_id,
        timestamp=datetime.now(timezone.utc),
        mode="normal",
        event="repaired",
        sensors=SensorReadings(**sensors),
        sensor_location=req.sensor_location,
        humidity_context=req.humidity_context,
        is_repair=True,
        source=f"technician_repair:{tech_id}",
    )

    ingestion_result = await ingest_sensor_data(sensor_in)

    # Clear active simulator state for this unit
    for k in list(_simulators.keys()):
        if k.startswith(req.hvac_id):
            _simulators.pop(k, None)

    return {
        "success": True,
        "message": f"HVAC Unit {req.hvac_id} successfully serviced and repaired by {tech_id}. Refrigerant recharged, cooling restored.",
        "repaired_by": tech_id,
        "sensors": sensors,
        "location_metadata": meta,
        "ai_result": ingestion_result.get("ai_result"),
        "critical_estimation": ingestion_result.get("critical_estimation"),
    }


@router.post("/reset/{hvac_id}")
def reset_simulation(hvac_id: str):
    """
    Reset AI pipeline state, LSTM buffer, and trend estimator for the specified HVAC unit.
    """
    pipeline_manager.reset_hvac_state(hvac_id)
    for k in list(_simulators.keys()):
        if k.startswith(hvac_id):
            _simulators.pop(k, None)

    return {"success": True, "message": f"State reset for {hvac_id}"}
