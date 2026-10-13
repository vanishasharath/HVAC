"""
Sensor ingestion, now connected to the REAL AI pipeline.

Flow per incoming reading:
  1. Store raw reading in InfluxDB
  2. Feed the 5 raw values into pipeline_manager.process_reading(...)
     -> engineers the 10-feature row
     -> maintains the 36-reading LSTM buffer
     -> maintains the anomaly-duration counter
     -> runs Isolation Forest -> LSTM -> Random Forest
  3. Broadcast the real sensor reading to connected frontend dashboards
     through the HVAC WebSocket
  4. Hand the real pipeline result to the alert engine

Both AI and alert processing are wrapped defensively so that a failure
in those components does not make sensor ingestion fail.
"""

import logging

from influxdb_client import Point

from app.ai.pipeline_manager import pipeline_manager
from app.database.influxdb import write_sensor_point
from app.schemas.sensor import SensorDataIn
from app.websocket.manager import manager

logger = logging.getLogger("sensor_ingestion")


async def ingest_sensor_data(data: SensorDataIn) -> dict:
    # ---------------------------------------------------------
    # 1. Store the raw sensor reading in InfluxDB
    # ---------------------------------------------------------
    point = (
        Point("hvac_telemetry")
        .tag("device_id", data.device_id)
        .tag("hvac_id", data.hvac_id)
        .tag("mode", data.mode)
        .tag("source", data.source)
        .time(data.timestamp)
    )

    sensor_values = data.sensors.model_dump(exclude_none=True)

    for field_name, value in sensor_values.items():
        point = point.field(field_name, value)

    if data.edge_anomaly_score is not None:
        point = point.field("edge_anomaly_score", data.edge_anomaly_score)

    if data.event:
        point = point.tag("event", data.event)

    write_sensor_point(point)

    # ---------------------------------------------------------
    # 2. Broadcast the real sensor reading to WebSocket clients
    # ---------------------------------------------------------
    try:
        await manager.broadcast_to_hvac(
            data.hvac_id,
            "sensor_reading",
            {
                "device_id": data.device_id,
                "timestamp": data.timestamp,
                "sensors": sensor_values,
                "mode": data.mode,
                "source": data.source,
            },
        )
    except Exception as exc:
        logger.error(
            "WebSocket broadcast failed for hvac_id=%s: %s",
            data.hvac_id,
            exc,
        )

    # ---------------------------------------------------------
    # 3. Run the real AI pipeline
    # ---------------------------------------------------------
    pipeline_result = None

    try:
        pipeline_result = await _run_real_ai_pipeline(data)
    except Exception as exc:
        logger.error(
            "AI pipeline failed for hvac_id=%s: %s",
            data.hvac_id,
            exc,
        )

    # ---------------------------------------------------------
    # 4. Evaluate the AI result and create alerts
    # ---------------------------------------------------------
    if pipeline_result is not None:
        try:
            await _evaluate_alert(data.hvac_id, pipeline_result)
        except Exception as exc:
            logger.error(
                "Alert evaluation failed for hvac_id=%s: %s",
                data.hvac_id,
                exc,
            )

    # ---------------------------------------------------------
    # 5. Return ingestion result
    # ---------------------------------------------------------
    return {
        "status": "stored",
        "device_id": data.device_id,
        "hvac_id": data.hvac_id,
        "timestamp": data.timestamp,
        "ai_result": pipeline_result,
    }


async def _run_real_ai_pipeline(data: SensorDataIn) -> dict:
    raw_reading = {
        "gas_ppm": data.sensors.gas_ppm or 0.0,
        "pressure": data.sensors.pressure or 0.0,
        "temperature": data.sensors.temperature or 0.0,
        "humidity": data.sensors.humidity or 0.0,
        "compressor_current": data.sensors.compressor_current or 0.0,
    }

    # process_reading is synchronous CPU-bound work
    # (sklearn/keras inference). This is acceptable for the
    # current academic prototype request volume.
    #
    # A production system could move this work to a thread pool
    # to avoid blocking the async event loop.
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