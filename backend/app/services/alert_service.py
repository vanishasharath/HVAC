"""
Alert engine, now driven by the REAL Random Forest severity classifier
instead of manual score thresholds.

WHY THE MAPPING BELOW EXISTS: your project report and existing frontend
use 3 alert tiers (WARNING / PREDICTIVE / CRITICAL). Your teammate's real
Random Forest was trained on 4 severity classes (Low / Medium / High /
Critical), which is a different, more granular scheme. Both are legitimate
- the RF's 4 classes are the actual trained model output; the report's 3
tiers are what your dashboard/alerts are documented to use. Rather than
silently picking one, this is the explicit reconciliation:

    RF "Low"      -> no alert created (healthy / not yet worth flagging)
    RF "Medium"   -> WARNING
    RF "High"     -> PREDICTIVE
    RF "Critical" -> CRITICAL

This is a BACKEND IMPLEMENTATION DECISION, not something either of your
original specs stated - flag it in your report/viva as a deliberate
reconciliation between the ML output granularity and the report's alert
terminology, not an oversight.
"""

from datetime import datetime, timedelta, timezone

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, status

from app.database.mongodb import get_database
from app.services.notification_service import notification_service
from app.websocket.manager import manager


# Prevent repeated alerts for the same HVAC unit/severity
# within this time window.
_DEDUP_WINDOW_MINUTES = 10


SEVERITY_TIER_MAP = {
    "Low": None,          # no alert
    "Medium": "WARNING",
    "High": "PREDICTIVE",
    "Critical": "CRITICAL",
}


def _serialize(alert: dict) -> dict:
    alert = dict(alert)
    alert["id"] = str(alert.pop("_id"))
    return alert


async def _has_recent_active_alert(hvac_id: str, severity: str) -> bool:
    db = get_database()

    cutoff = datetime.now(timezone.utc) - timedelta(
        minutes=_DEDUP_WINDOW_MINUTES
    )

    existing = await db.alerts.find_one(
        {
            "hvac_id": hvac_id,
            "severity": severity,
            "status": "ACTIVE",
            "created_at": {"$gte": cutoff},
        }
    )

    return existing is not None


async def evaluate_and_create_alert_from_pipeline_result(
    hvac_id: str,
    pipeline_result: dict,
    source: str = "ingestion_pipeline",
) -> dict | None:
    """
    pipeline_result: the exact dict returned by
    app.ai.pipeline_manager.pipeline_manager.process_reading(), i.e.

    {
        anomaly_score,
        anomaly_flag,
        anomaly_duration,
        lstm_prob_24hr,
        lstm_prob_48hr,
        severity,
        severity_confidence,
        feature_row
    }

    Returns the created alert dict, or None if:

    - RF said "Low" (no alert), or
    - an active alert of the same tier was created recently
      for this HVAC unit.
    """

    rf_severity = pipeline_result["severity"]

    # Convert RF's 4 severity classes into the dashboard's
    # 3 alert tiers.
    tier = SEVERITY_TIER_MAP.get(rf_severity)

    # Low severity does not create an alert.
    if tier is None:
        return None

    # Check for a recent active alert for ALL severity levels,
    # including CRITICAL.
    #
    # This prevents one ongoing leak from creating dozens of
    # identical CRITICAL alerts.
    if await _has_recent_active_alert(hvac_id, tier):
        return None

    db = get_database()

    alert_doc = {
        "hvac_id": hvac_id,
        "severity": tier,
        "status": "ACTIVE",
        "source": source,
        "message": f"Refrigerant leak {tier} alert on {hvac_id}",
        "description": (
            f"AI Model detected leak: RF severity={rf_severity} "
            f"(confidence {pipeline_result.get('severity_confidence')}), "
            f"anomaly_score={pipeline_result.get('anomaly_score')}"
        ),

        # Real Random Forest result
        "rf_severity": rf_severity,
        "rf_confidence": pipeline_result.get("severity_confidence"),

        # Real anomaly detection result
        "anomaly_score": pipeline_result.get("anomaly_score"),
        "anomaly_flag": pipeline_result.get("anomaly_flag"),
        "anomaly_duration": pipeline_result.get("anomaly_duration"),

        # Real LSTM forecast results
        "lstm_prob_24hr": pipeline_result.get("lstm_prob_24hr"),
        "lstm_prob_48hr": pipeline_result.get("lstm_prob_48hr"),

        # Alert lifecycle fields
        "created_at": datetime.now(timezone.utc),
        "resolved_at": None,
        "resolved_by": None,
    }

    # Store alert in MongoDB
    result = await db.alerts.insert_one(alert_doc)

    alert_doc["_id"] = result.inserted_id

    serialized = _serialize(alert_doc)

    # Notify connected dashboard clients
    try:
        await manager.broadcast_to_hvac(
            hvac_id,
            "alert_created",
            serialized,
        )
    except Exception:
        pass

    # Send notification
    try:
        await notification_service.notify(
            recipient=f"facility-manager:{hvac_id}",
            title=f"{tier} alert - {hvac_id}",
            message=(
                f"RF severity={rf_severity} "
                f"(confidence {pipeline_result.get('severity_confidence')}), "
                f"anomaly_score={pipeline_result.get('anomaly_score')}, "
                f"lstm_24hr={pipeline_result.get('lstm_prob_24hr')}, "
                f"lstm_48hr={pipeline_result.get('lstm_prob_48hr')}"
            ),
        )
    except Exception:
        pass

    return serialized


async def evaluate_and_create_alert_from_edge(
    hvac_id: str,
    event: str = "WARNING",
    gas_alert: bool = True,
    device_id: str = "ESP32",
    details: dict | None = None,
) -> dict | None:
    """
    Creates an alert when edge hardware (e.g. ESP32 MQ-5 sensor) flags a gas alert
    or warning/risk status.
    """
    event_upper = (event or "").upper()
    if event_upper in ["HIGH RISK", "CRITICAL"]:
        tier = "CRITICAL"
    elif event_upper == "PREDICTIVE":
        tier = "PREDICTIVE"
    else:
        tier = "WARNING"

    if await _has_recent_active_alert(hvac_id, tier):
        return None

    db = get_database()

    alert_doc = {
        "hvac_id": hvac_id,
        "severity": tier,
        "status": "ACTIVE",
        "source": "edge_hardware",
        "message": f"Gas leak alert ({tier}) detected by MQ-5 sensor on {hvac_id}",
        "description": f"Hardware sensor triggered refrigerant gas alert. Event: {event}",
        "device_id": device_id,
        "rf_severity": None,
        "rf_confidence": None,
        "anomaly_score": None,
        "anomaly_flag": 1,
        "anomaly_duration": None,
        "lstm_prob_24hr": None,
        "lstm_prob_48hr": None,
        "details": details or {},
        "created_at": datetime.now(timezone.utc),
        "resolved_at": None,
        "resolved_by": None,
    }

    result = await db.alerts.insert_one(alert_doc)
    alert_doc["_id"] = result.inserted_id

    serialized = _serialize(alert_doc)

    try:
        await manager.broadcast_to_hvac(
            hvac_id,
            "alert_created",
            serialized,
        )
    except Exception:
        pass

    try:
        await notification_service.notify(
            recipient=f"facility-manager:{hvac_id}",
            title=f"{tier} Gas Alert - {hvac_id}",
            message=f"MQ-5 Gas sensor detected refrigerant leak risk. Event: {event}",
        )
    except Exception:
        pass

    return serialized


async def list_alerts(
    hvac_id: str | None = None,
    status_filter: str | None = None,
) -> list:
    db = get_database()

    query = {}

    if hvac_id:
        query["hvac_id"] = hvac_id

    if status_filter:
        query["status"] = status_filter

    alerts = (
        await db.alerts
        .find(query)
        .sort("created_at", -1)
        .to_list(length=200)
    )

    return [_serialize(a) for a in alerts]


async def get_alert(alert_id: str) -> dict:
    db = get_database()

    try:
        oid = ObjectId(alert_id)
    except InvalidId:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid alert id",
        )

    alert = await db.alerts.find_one({"_id": oid})

    if not alert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert not found",
        )

    return _serialize(alert)


async def resolve_alert(
    alert_id: str,
    resolved_by: str,
    resolution_note: str | None = None,
) -> dict:
    db = get_database()

    try:
        oid = ObjectId(alert_id)
    except InvalidId:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid alert id",
        )

    update = {
        "status": "RESOLVED",
        "resolved_at": datetime.now(timezone.utc),
        "resolved_by": resolved_by,
    }

    if resolution_note:
        update["resolution_note"] = resolution_note

    result = await db.alerts.update_one(
        {"_id": oid},
        {"$set": update},
    )

    if result.matched_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert not found",
        )

    updated = await get_alert(alert_id)

    # Notify dashboard clients that the alert was resolved
    try:
        await manager.broadcast_to_hvac(
            updated["hvac_id"],
            "alert_resolved",
            updated,
        )
    except Exception:
        pass

    return updated