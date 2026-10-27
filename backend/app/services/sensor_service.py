
import logging

from app.ai.pipeline_manager import pipeline_manager
from app.schemas.sensor import SensorDataIn
from app.websocket.manager import manager

logger = logging.getLogger("sensor_ingestion")


async def ingest_sensor_data(data: SensorDataIn) -> dict:
    # 0. Check edge alert states
    temp_val = data.sensors.temperature
    event_str = (data.event or "").upper()

    # Temperature alert: explicit flag, or TEMP in event, or temp >= 30 with warning status, or temp >= 35.0
    is_edge_temp_alert = bool(
        data.temperature_alert
        or ("TEMP" in event_str)
        or (temp_val is not None and temp_val >= 30.0 and event_str in ["WARNING", "HIGH RISK"])
        or (temp_val is not None and temp_val >= 35.0)
    )

    # Gas alert: explicit gas_alert flag, or GAS in event.
    # If gas_alert is False, it is explicitly NOT a gas alert.
    # If gas_alert is None and event is WARNING/HIGH RISK without it being a temp alert, consider it gas.
    if data.gas_alert is not None:
        is_edge_gas_alert = bool(data.gas_alert)
    elif "GAS" in event_str:
        is_edge_gas_alert = True
    elif event_str in ["WARNING", "HIGH RISK", "CRITICAL"] and not is_edge_temp_alert:
        is_edge_gas_alert = True
    else:
        is_edge_gas_alert = False

    # If gas_ppm was not provided directly, calculate or provide realistic value
    if data.sensors.gas_ppm is None:
        if data.sensors.mq5_adc is not None:
            baseline = 1461.0
            excess = max(0.0, float(data.sensors.mq5_adc) - baseline)
            data.sensors.gas_ppm = round(5.0 + excess * 0.8, 2)
        elif is_edge_gas_alert:
            data.sensors.gas_ppm = 180.0 if event_str == "WARNING" else 350.0
        else:
            data.sensors.gas_ppm = 5.0

    # 1. Prepare the sensor values
    sensor_values = data.sensors.model_dump(exclude_none=True)
    if "gas_ppm" not in sensor_values and data.sensors.gas_ppm is not None:
        sensor_values["gas_ppm"] = data.sensors.gas_ppm

    # 2. Skip InfluxDB storage
    # The reading continues to the AI pipeline and dashboard.
    logger.info(
        "InfluxDB bypassed for device_id=%s, hvac_id=%s",
        data.device_id,
        data.hvac_id,
    )

    # 3. Run the real AI pipeline first so predictions & critical condition estimations
    # are immediately available for WebSocket broadcast and alerts
    pipeline_result = None
    try:
        pipeline_result = await _run_real_ai_pipeline(data)
    except Exception:
        logger.exception(
            "AI pipeline failed for hvac_id=%s",
            data.hvac_id,
        )

    # 4. Broadcast the sensor reading and AI critical estimation to connected dashboards
    sensor_loc = data.sensor_location or getattr(data.sensors, "sensor_location", "suction_line")
    try:
        await manager.broadcast_to_hvac(
            data.hvac_id,
            "sensor_reading",
            {
                "device_id": data.device_id,
                "timestamp": data.timestamp.isoformat(),
                "sensors": sensor_values,
                "mode": data.mode,
                "source": data.source,
                "event": data.event,
                "sensor_location": sensor_loc,
                "humidity_context": data.humidity_context,
                "gas_alert": is_edge_gas_alert,
                "temperature_alert": is_edge_temp_alert,
                "ai_result": pipeline_result,
                "critical_estimation": pipeline_result.get("critical_estimation") if pipeline_result else None,
            },
        )
    except Exception:
        logger.exception(
            "WebSocket broadcast failed for hvac_id=%s",
            data.hvac_id,
        )

    # 5. If edge hardware triggered alerts, evaluate edge alerts
    if is_edge_temp_alert:
        try:
            from app.services.alert_service import evaluate_and_create_alert_from_edge
            await evaluate_and_create_alert_from_edge(
                hvac_id=data.hvac_id,
                event=data.event or "WARNING",
                alert_type="temperature",
                device_id=data.device_id,
                details={"temperature": temp_val, "sensors": sensor_values},
            )
        except Exception:
            logger.exception(
                "Temperature alert evaluation failed for hvac_id=%s",
                data.hvac_id,
            )

    if is_edge_gas_alert:
        try:
            from app.services.alert_service import evaluate_and_create_alert_from_edge
            await evaluate_and_create_alert_from_edge(
                hvac_id=data.hvac_id,
                event=data.event or "WARNING",
                alert_type="gas",
                device_id=data.device_id,
                details={"sensors": sensor_values},
            )
        except Exception:
            logger.exception(
                "Edge alert evaluation failed for hvac_id=%s",
                data.hvac_id,
            )

    # If this reading is a repair event, resolve all active alerts for this HVAC unit
    is_repair = bool(data.is_repair or (data.event and data.event.lower() in ["repaired", "maintenance_completed"]))
    if is_repair:
        try:
            from app.services.alert_service import resolve_all_active_alerts_for_hvac
            await resolve_all_active_alerts_for_hvac(data.hvac_id)
        except Exception:
            logger.exception("Failed to auto-resolve alerts on repair for hvac_id=%s", data.hvac_id)

    # 6. Evaluate alerts when the AI pipeline returns a result (skip if just repaired)
    if pipeline_result is not None and not is_repair:
        try:
            await _evaluate_alert(data.hvac_id, pipeline_result)
        except Exception:
            logger.exception(
                "Alert evaluation failed for hvac_id=%s",
                data.hvac_id,
            )

    # 7. Return the ingestion result
    return {
        "status": "received",
        "storage": "influxdb_bypassed",
        "device_id": data.device_id,
        "hvac_id": data.hvac_id,
        "timestamp": data.timestamp.isoformat(),
        "ai_result": pipeline_result,
        "edge_alert": (is_edge_gas_alert or is_edge_temp_alert) if not is_repair else False,
        "temperature_alert": is_edge_temp_alert if not is_repair else False,
        "gas_alert": is_edge_gas_alert if not is_repair else False,
        "critical_estimation": pipeline_result.get("critical_estimation") if pipeline_result else None,
        "is_repaired": is_repair,
    }


async def _run_real_ai_pipeline(data: SensorDataIn) -> dict:
    sensor_loc = data.sensor_location or getattr(data.sensors, "sensor_location", "suction_line")
    is_repair = bool(data.is_repair or (data.event and data.event.lower() in ["repaired", "maintenance_completed"]))
    raw_reading = {
        "gas_ppm": (
            data.sensors.gas_ppm
            if data.sensors.gas_ppm is not None
            else 0.0
        ),
        "pressure": (
            data.sensors.pressure
            if data.sensors.pressure is not None
            else 0.0
        ),
        "temperature": (
            data.sensors.temperature
            if data.sensors.temperature is not None
            else 0.0
        ),
        "humidity": (
            data.sensors.humidity
            if data.sensors.humidity is not None
            else 0.0
        ),
        "compressor_current": (
            data.sensors.compressor_current
            if data.sensors.compressor_current is not None
            else 0.0
        ),
    }

    # Real model inference with trend and critical condition estimation (in hours)
    return pipeline_manager.process_reading(
        hvac_id=data.hvac_id,
        raw_reading=raw_reading,
        sensor_location=sensor_loc,
        timestamp=data.timestamp,
        simulated_operating_seconds=data.simulated_operating_seconds,
        is_repair=is_repair,
    )


async def _evaluate_alert(
    hvac_id: str,
    pipeline_result: dict,
) -> None:
    from app.services.alert_service import (
        evaluate_and_create_alert_from_pipeline_result,
    )

    await evaluate_and_create_alert_from_pipeline_result(
        hvac_id,
        pipeline_result,
    )
