"""
GET /predict surfaces the real Isolation Forest's most recent output for
this HVAC unit - the cached result from the last ingested reading, not a
fresh re-run (the real pipeline is stateful; only ingestion should advance
its buffer/anomaly-duration counter).
"""

from datetime import datetime, timezone

from fastapi import HTTPException, status

from app.ai.pipeline_manager import pipeline_manager


async def predict_anomaly(hvac_id: str) -> dict:
    result = pipeline_manager.get_last_result(hvac_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No sensor readings have been ingested yet for hvac_id={hvac_id}",
        )

    return {
        "hvac_id": hvac_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "anomaly_score": result["anomaly_score"],
        "anomaly_flag": result["anomaly_flag"],
        "anomaly_duration": result["anomaly_duration"],
        "severity": result.get("severity"),
        "severity_confidence": result.get("severity_confidence"),
        "status": "ANOMALY" if result["anomaly_flag"] == 1 else "NORMAL",
        "critical_estimation": result.get("critical_estimation"),
    }
