from datetime import datetime, timedelta, timezone
from app.ai.trend_estimator import AITrendCriticalEstimator, CRITICAL_THRESHOLDS


def test_trend_estimator_healthy():
    estimator = AITrendCriticalEstimator(window_size=20)
    now = datetime.now(timezone.utc)
    for i in range(10):
        t = now + timedelta(seconds=i * 10)
        reading = {
            "gas_ppm": 5.0,
            "temperature": 7.0,
            "pressure": 165.0,
            "humidity": 55.0,
            "compressor_current": 6.0,
        }
        est = estimator.update(reading, timestamp=t)

    assert est["status"] == "HEALTHY_STABLE"
    assert est["critical_reached"] is False
    assert est["time_to_critical_seconds"] is None


def test_trend_estimator_progressing_leak():
    estimator = AITrendCriticalEstimator(window_size=30)
    now = datetime.now(timezone.utc)

    # Ingest 15 steps with steady leak progression
    # gas increases by 10 ppm each step (1 ppm/sec)
    # temp rises by 0.3 C each step (0.03 C/sec)
    # pressure drops by 1.5 psi each step (-0.15 psi/sec)
    for i in range(15):
        t = now + timedelta(seconds=i * 10)
        reading = {
            "gas_ppm": 5.0 + i * 10.0,           # reaches 145 ppm
            "temperature": 7.0 + i * 0.3,         # reaches 11.2 C
            "pressure": 165.0 - i * 1.5,         # reaches 144 psi
            "humidity": 55.0 + (i % 2) * 0.5,    # contextual humidity oscillation
            "compressor_current": 6.0 + i * 0.1,
        }
        ai_res = {
            "severity": "Medium" if i > 5 else "Low",
            "anomaly_flag": 1 if i > 5 else 0,
            "anomaly_duration": i - 5 if i > 5 else 0,
            "lstm_prob_24hr": 0.2,
        }
        est = estimator.update(reading, ai_pipeline_result=ai_res, timestamp=t)

    assert est["status"] == "LEAK_PROGRESSING"
    assert est["critical_reached"] is False
    assert est["time_to_critical_seconds"] is not None
    assert est["time_to_critical_seconds"] > 0
    assert est["time_to_critical_hours"] is not None
    assert est["time_to_critical_hours"] > 0
    assert est["elapsed_time_seconds"] > 0
    assert est["trends"]["gas_ppm_per_hour"] > 10.0
    assert est["trends"]["temp_per_hour"] > 0.1
    assert est["trends"]["pressure_per_hour"] < 0
    assert "projected_critical_time" in est


def test_trend_estimator_critical_reached():
    estimator = AITrendCriticalEstimator(window_size=20)
    now = datetime.now(timezone.utc)
    reading = {
        "gas_ppm": 410.0,  # exceeds 400 ppm
        "temperature": 23.5,
        "pressure": 98.0,
        "humidity": 55.0,
        "compressor_current": 9.5,
    }
    ai_res = {
        "severity": "Critical",
        "anomaly_flag": 1,
        "anomaly_duration": 30,
        "lstm_prob_24hr": 0.95,
    }
    est = estimator.update(reading, ai_pipeline_result=ai_res, timestamp=now)
    assert est["status"] == "CRITICAL_REACHED"
    assert est["critical_reached"] is True
    assert est["time_to_critical_seconds"] == 0.0
