"""
GET /forecast surfaces the real LSTM's most recent 24hr/48hr leak
probability for this HVAC unit - both default to 0.0 until at least 36
readings (LSTM_WINDOW_SIZE) have been ingested for that unit, exactly
matching SensorStream's own behavior in the real pipeline.
"""

from datetime import datetime, timezone

from fastapi import HTTPException, status

from app.ai.pipeline_manager import pipeline_manager


async def forecast_leak_probability(hvac_id: str) -> dict:
    result = pipeline_manager.get_last_result(hvac_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No sensor readings have been ingested yet for hvac_id={hvac_id}",
        )

    stream = pipeline_manager._streams.get(hvac_id)
    window_filled = stream is not None and len(stream.buffer) >= 36

    return {
        "hvac_id": hvac_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "lstm_prob_24hr": result["lstm_prob_24hr"],
        "lstm_prob_48hr": result["lstm_prob_48hr"],
        "forecast_ready": window_filled,
        "readings_buffered": len(stream.buffer) if stream else 0,
        "critical_estimation": result.get("critical_estimation"),
    }
