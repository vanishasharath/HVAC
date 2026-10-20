
import logging

from app.ai.pipeline_manager import pipeline_manager
from app.schemas.sensor import SensorDataIn
from app.websocket.manager import manager

logger = logging.getLogger("sensor_ingestion")


async def ingest_sensor_data(data: SensorDataIn) -> dict:
    # 0. Check if edge hardware reported a gas alert or risk condition
    is_edge_gas_alert = bool(
        data.gas_alert
        or (data.event and data.event.upper() in ["WARNING", "HIGH RISK", "GAS ALERT", "CRITICAL"])
    )

    # If gas_ppm was not provided directly, calculate or provide realistic value
    if data.sensors.gas_ppm is None:
        if data.sensors.mq5_adc is not None:
            baseline = 1461.0
            excess = max(0.0, float(data.sensors.mq5_adc) - baseline)
            data.sensors.gas_ppm = round(5.0 + excess * 0.8, 2)
        elif is_edge_gas_alert:
            data.sensors.gas_ppm = 180.0 if (data.event and data.event.upper() == "WARNING") else 350.0
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

    # 3. Broadcast the real sensor reading to connected dashboards
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
                "gas_alert": is_edge_gas_alert,
            },
        )
    except Exception:
        logger.exception(
            "WebSocket broadcast failed for hvac_id=%s",
            data.hvac_id,
        )

    # 4. If edge hardware triggered an alert, evaluate edge alert
    if is_edge_gas_alert:
        try:
            from app.services.alert_service import evaluate_and_create_alert_from_edge
            await evaluate_and_create_alert_from_edge(
                hvac_id=data.hvac_id,
                event=data.event or "WARNING",
                gas_alert=True,
                device_id=data.device_id,
                details={"sensors": sensor_values},
            )
        except Exception:
            logger.exception(
                "Edge alert evaluation failed for hvac_id=%s",
                data.hvac_id,
            )

    # 5. Run the real AI pipeline
    pipeline_result = None

    try:
        pipeline_result = await _run_real_ai_pipeline(data)
    except Exception:
        logger.exception(
            "AI pipeline failed for hvac_id=%s",
            data.hvac_id,
        )

    # 6. Evaluate alerts when the AI pipeline returns a result
    if pipeline_result is not None:
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
        "edge_alert": is_edge_gas_alert,
    }


async def _run_real_ai_pipeline(data: SensorDataIn) -> dict:
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

    # Real model inference; no simulated prediction is added here.
    return pipeline_manager.process_reading(
        data.hvac_id,
        raw_reading,
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
