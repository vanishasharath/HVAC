from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class AlertSeverity(str, Enum):
    """
    Report-facing 3-tier terminology (matches project spec/report language).
    Mapped from the real Random Forest's Low/Medium/High/Critical output -
    see alert_service.SEVERITY_TIER_MAP for the exact mapping and the
    reasoning behind it.
    """
    WARNING = "WARNING"
    PREDICTIVE = "PREDICTIVE"
    CRITICAL = "CRITICAL"


class AlertStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESOLVED = "RESOLVED"


class AlertOut(BaseModel):
    id: str
    hvac_id: str
    severity: AlertSeverity
    status: AlertStatus
    source: str
    message: Optional[str] = None
    description: Optional[str] = None

    # Raw outputs from the REAL pipeline (app/ai/real_pipeline.py) -
    # kept alongside the mapped `severity` tier above so nothing from the
    # model's actual output is lost.
    rf_severity: Optional[str] = None          # "Low" | "Medium" | "High" | "Critical" - RF's own label
    rf_confidence: Optional[float] = None       # RF's predict_proba for the chosen class
    anomaly_score: Optional[float] = None       # raw Isolation Forest score, NOT bounded [0,1]
    anomaly_flag: Optional[int] = None          # 0 or 1
    anomaly_duration: Optional[int] = None      # consecutive anomalous readings
    lstm_prob_24hr: Optional[float] = None
    lstm_prob_48hr: Optional[float] = None

    created_at: datetime
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None


class AlertResolveRequest(BaseModel):
    resolution_note: Optional[str] = None
