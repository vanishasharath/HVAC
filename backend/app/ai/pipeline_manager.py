"""
Manages one (StreamingFeatureEngineer, SensorStream) pair per HVAC unit.

WHY THIS EXISTS: the real pipeline (app/ai/real_pipeline.py, unmodified
from your ML teammate) needs two kinds of state per unit that a stateless
FastAPI request can't carry on its own:
  1. A 36-reading buffer for the LSTM (SensorStream.buffer)
  2. A running anomaly-duration counter (SensorStream.anomaly_duration)

This backend also needs a third kind of state your teammate's script
didn't need to worry about (it read a whole CSV at once): the previous
raw reading and a 30-sample gas_ppm window, to compute rate-of-change and
rolling stats one reading at a time (StreamingFeatureEngineer).

PERSISTENCE LIMITATION - read before your demo: this state lives in a
plain Python dict, in-memory, in this one process. It resets if the
server restarts, and does NOT work correctly if you run multiple uvicorn
worker processes (each worker would have its own separate state, silently
giving each HVAC unit multiple independent, inconsistent LSTM buffers).
This is fine for a single-process academic demo. Your teammate's own
SensorStream docstring says production would use Redis per-unit - that
is the correct fix if this ever needs multiple workers or restarts
without losing the leak-in-progress state, and is flagged here as a
BACKEND IMPLEMENTATION DECISION for later, not solved by this delivery.
"""

import logging
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from app.ai.feature_engineering import StreamingFeatureEngineer
from app.ai.real_pipeline import LeakDetectionPipeline, SensorStream
from app.ai.trend_estimator import AITrendCriticalEstimator
from app.config import settings

logger = logging.getLogger("ai.pipeline_manager")


class PipelineManager:
    def __init__(self, models_dir: str = None):
        models_dir = models_dir or settings.model_dir
        self._models_dir = str(Path(models_dir))
        self._pipeline: LeakDetectionPipeline = None
        self._streams: Dict[str, SensorStream] = {}
        self._feature_engineers: Dict[str, StreamingFeatureEngineer] = {}
        self._trend_estimators: Dict[str, AITrendCriticalEstimator] = {}
        self._last_results: Dict[str, dict] = {}
        self._load_error: str = None

        try:
            self._pipeline = LeakDetectionPipeline(models_dir=self._models_dir)
            logger.info("Real AI pipeline loaded from %s", self._models_dir)
        except Exception as exc:
            # Loading is attempted once at startup. If the 4 model files
            # aren't present (e.g. someone runs this backend without
            # copying models/ over), we log clearly and every prediction
            # call raises a clear error instead of crashing app startup.
            self._load_error = str(exc)
            logger.error(
                "Failed to load real AI pipeline from %s: %s. "
                "Predictions will fail until this is fixed.",
                self._models_dir, exc,
            )

    @property
    def is_loaded(self) -> bool:
        return self._pipeline is not None

    def _get_or_create(self, hvac_id: str):
        if hvac_id not in self._streams:
            self._streams[hvac_id] = SensorStream(self._pipeline)
            self._feature_engineers[hvac_id] = StreamingFeatureEngineer()
            self._trend_estimators[hvac_id] = AITrendCriticalEstimator()
        return self._feature_engineers[hvac_id], self._streams[hvac_id], self._trend_estimators[hvac_id]

    def process_reading(
        self,
        hvac_id: str,
        raw_reading: dict,
        sensor_location: str = "suction_line",
        timestamp: Optional[datetime] = None,
        simulated_operating_seconds: Optional[float] = None,
        is_repair: bool = False,
    ) -> dict:
        """
        raw_reading: dict with gas_ppm, pressure, temperature, humidity,
        compressor_current (the 5 fields the backend already ingests).

        Returns the real pipeline's full result dict augmented with:
            anomaly_score, anomaly_flag, anomaly_duration,
            lstm_prob_24hr, lstm_prob_48hr, severity, severity_confidence,
            critical_estimation (AI trend analysis in hours, elapsed time, and ETTC)
        """
        if not self.is_loaded:
            raise RuntimeError(
                f"AI pipeline is not loaded (models_dir={self._models_dir}): {self._load_error}"
            )

        feature_engineer, stream, estimator = self._get_or_create(hvac_id)

        # If this is a repair event, also reset the stream's anomaly duration
        if is_repair:
            stream.anomaly_duration = 0

        feature_row = feature_engineer.push_raw_reading(raw_reading)
        result = stream.push_reading(feature_row)
        result["feature_row"] = feature_row

        # Compute AI trend analysis and elapsed time to critical condition (in hours)
        trend_estimate = estimator.update(
            raw_reading=raw_reading,
            ai_pipeline_result=result,
            timestamp=timestamp,
            sensor_location=sensor_location,
            simulated_operating_seconds=simulated_operating_seconds,
            is_repair=is_repair,
        )
        result["critical_estimation"] = trend_estimate

        self._last_results[hvac_id] = result
        return result

    def get_last_result(self, hvac_id: str) -> dict:
        """Returns the most recent real pipeline output for this unit, or
        None if no reading has been ingested for it yet."""
        return self._last_results.get(hvac_id)

    def reset_hvac_state(self, hvac_id: str) -> None:
        """Clears buffered state for one unit - e.g. after a confirmed repair."""
        self._streams.pop(hvac_id, None)
        self._feature_engineers.pop(hvac_id, None)
        if hvac_id in self._trend_estimators:
            self._trend_estimators[hvac_id].reset()
            self._trend_estimators.pop(hvac_id, None)
        self._last_results.pop(hvac_id, None)


# Single shared instance, loaded once at import time.
pipeline_manager = PipelineManager()
