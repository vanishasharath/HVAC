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

import logging
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, status

from app.database.mongodb import get_database
from app.services.notification_service import notification_service
from app.websocket.manager import manager

logger = logging.getLogger("alerts")


# Prevent repeated alerts for the same HVAC unit/severity
# within this time window (tuned to 1 minute for responsive real-time testing).
_DEDUP_WINDOW_MINUTES = 1


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


async def _send_admin_sms_for_alert(
    hvac_id: str,
    severity_label: str,
    tier: str,
    summary_text: str = "",
    alert_id: str | ObjectId | None = None,
) -> None:
    """
    Identifies Admin users with registered phone numbers in MongoDB,
    and sends SMS notifications via TextBee/Twilio without failing the main flow.
    Ensures SMS is sent once per critical leak event (60-second flood protection).
    """
    try:
        db = get_database()
        if db is None:
            return

        # Check if an SMS was ALREADY sent for an ongoing ACTIVE alert within the last 60 seconds.
        # This prevents spamming on continuous 5-second sensor uploads while allowing live testing.
        recent_cutoff = datetime.now(timezone.utc) - timedelta(seconds=60)
        existing_active_sms = await db.alerts.find_one({
            "hvac_id": hvac_id,
            "status": "ACTIVE",
            "sms_sent": True,
            "created_at": {"$gte": recent_cutoff},
        })
        if existing_active_sms:
            logger.info(
                "SMS already sent recently for active alert on %s (Alert ID: %s); skipping duplicate SMS.",
                hvac_id,
                existing_active_sms.get("_id"),
            )
            return

        cursor = db.users.find({
            "role": "ADMIN",
            "phone_number": {"$exists": True, "$ne": None, "$ne": ""},
        })
        admins = await cursor.to_list(length=100)

        if not admins:
            logger.warning(
                "No Admin account with a registered phone number found in MongoDB; SMS alert skipped for %s alert on %s",
                severity_label,
                hvac_id,
            )
            return

        # Deduplicate phone numbers so multiple Admin accounts sharing a number receive ONLY ONE SMS
        unique_phones = []
        seen_phones = set()
        for admin in admins:
            phone = admin.get("phone_number")
            if phone and phone not in seen_phones:
                seen_phones.add(phone)
                unique_phones.append(phone)

        if not unique_phones:
            return

        title = f"CRITICAL HVAC ALERT: {hvac_id}" if tier == "CRITICAL" else f"HIGH LEAK RISK: {hvac_id}"
        message = (
            f"HVAC Unit {hvac_id} triggered a {severity_label} ({tier}) refrigerant alert. "
            f"Immediate inspection required. {summary_text}".strip()
        )

        sms_dispatched = False
        for phone in unique_phones:
            try:
                sent = await notification_service.send_sms(
                    recipient=phone,
                    title=title,
                    message=message,
                )
                if sent:
                    sms_dispatched = True
            except Exception as exc:
                logger.error("Failed to send admin alert SMS to %s: %s", phone, exc)

        # Mark sms_sent on the current alert document in MongoDB
        if sms_dispatched and alert_id:
            try:
                oid = ObjectId(alert_id) if not isinstance(alert_id, ObjectId) else alert_id
                await db.alerts.update_one({"_id": oid}, {"$set": {"sms_sent": True}})
            except Exception as exc:
                logger.warning("Failed to mark sms_sent on alert %s: %s", alert_id, exc)

    except Exception as exc:
        logger.error("Error during admin SMS alert dispatch: %s", exc)


async def _has_recent_active_alert(hvac_id: str, severity: str, alert_type: str | None = None) -> bool:
    db = get_database()
    if db is None:
        return False

    cutoff = datetime.now(timezone.utc) - timedelta(
        minutes=_DEDUP_WINDOW_MINUTES
    )

    query = {
        "hvac_id": hvac_id,
        "severity": severity,
        "status": "ACTIVE",
        "created_at": {"$gte": cutoff},
    }
    if alert_type:
        query["alert_type"] = alert_type

    existing = await db.alerts.find_one(query)

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
    if await _has_recent_active_alert(hvac_id, tier, alert_type="ai_leak"):
        return None

    db = get_database()
    if db is None:
        return None

    alert_doc = {
        "hvac_id": hvac_id,
        "severity": tier,
        "status": "ACTIVE",
        "source": source,
        "alert_type": "ai_leak",
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
        "sms_sent": False,
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

    # For High or Critical severity, send SMS alerts to all registered Admins (only once per incident)
    if rf_severity in ["High", "Critical"] or tier in ["PREDICTIVE", "CRITICAL"]:
        try:
            summary = (
                f"Confidence: {pipeline_result.get('severity_confidence')}, "
                f"Anomaly Score: {pipeline_result.get('anomaly_score')}"
            )
            await _send_admin_sms_for_alert(
                hvac_id=hvac_id,
                severity_label=rf_severity,
                tier=tier,
                summary_text=summary,
                alert_id=alert_doc["_id"],
            )
        except Exception:
            pass

    return serialized


async def evaluate_and_create_alert_from_edge(
    hvac_id: str,
    event: str = "WARNING",
    alert_type: str = "gas",
    device_id: str = "ESP32",
    details: dict | None = None,
) -> dict | None:
    """
    Creates an alert when edge hardware flags a condition (temperature, gas, etc).
    """
    event_upper = (event or "").upper()
    temp_val = details.get("temperature") if details else None

    if alert_type == "temperature":
        if event_upper in ["HIGH RISK", "CRITICAL"] or (temp_val is not None and temp_val >= 40.0):
            tier = "CRITICAL"
        else:
            tier = "WARNING"
        temp_str = f" ({temp_val:.1f}°C)" if temp_val is not None else ""
        message = f"High Temperature Alert ({tier}) on {hvac_id}{temp_str}"
        description = f"Hardware sensor reported abnormal temperature{temp_str}. Exceeds safe limit. Event: {event}"
        notify_title = f"{tier} Temperature Alert - {hvac_id}"
        notify_message = f"Temperature sensor reported abnormal temperature{temp_str}. Event: {event}"
    else:
        alert_type = "gas"
        if event_upper in ["HIGH RISK", "CRITICAL"]:
            tier = "CRITICAL"
        elif event_upper == "PREDICTIVE":
            tier = "PREDICTIVE"
        else:
            tier = "WARNING"
        message = f"Gas leak alert ({tier}) detected by MQ-5 sensor on {hvac_id}"
        description = f"Hardware sensor triggered refrigerant gas alert. Event: {event}"
        notify_title = f"{tier} Gas Alert - {hvac_id}"
        notify_message = f"MQ-5 Gas sensor detected refrigerant leak risk. Event: {event}"

    if await _has_recent_active_alert(hvac_id, tier, alert_type=alert_type):
        return None

    db = get_database()

    alert_doc = {
        "hvac_id": hvac_id,
        "severity": tier,
        "status": "ACTIVE",
        "source": "edge_hardware",
        "alert_type": alert_type,
        "message": message,
        "description": description,
        "device_id": device_id,
        "rf_severity": None,
        "rf_confidence": None,
        "anomaly_score": None,
        "anomaly_flag": 1,
        "anomaly_duration": None,
        "lstm_prob_24hr": None,
        "lstm_prob_48hr": None,
        "details": details or {},
        "sms_sent": False,
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
            title=notify_title,
            message=notify_message,
        )
    except Exception:
        pass

    # For CRITICAL hardware alerts, send SMS alerts to all registered Admins (only once per incident)
    if tier == "CRITICAL":
        try:
            await _send_admin_sms_for_alert(
                hvac_id=hvac_id,
                severity_label="Critical",
                tier=tier,
                summary_text=notify_message,
                alert_id=alert_doc["_id"],
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


async def resolve_all_active_alerts_for_hvac(
    hvac_id: str,
    resolved_by: str = "technician_service",
    resolution_note: str = "Leak repaired, system recharged and restored to healthy baseline",
) -> list:
    """Resolves all active alerts for the given HVAC unit (e.g. following repair)."""
    db = get_database()
    if db is None:
        return []
    now = datetime.now(timezone.utc)
    cursor = db.alerts.find({"hvac_id": hvac_id, "status": "ACTIVE"})
    active_alerts = await cursor.to_list(length=100)

    resolved = []
    for alert in active_alerts:
        aid = str(alert["_id"])
        await db.alerts.update_one(
            {"_id": alert["_id"]},
            {"$set": {"status": "RESOLVED", "resolved_at": now, "resolved_by": resolved_by, "resolution_note": resolution_note}},
        )
        updated = _serialize({**alert, "status": "RESOLVED", "resolved_at": now, "resolved_by": resolved_by})
        resolved.append(updated)
        try:
            await manager.broadcast_to_hvac(hvac_id, "alert_resolved", updated)
        except Exception:
            pass

    return resolved