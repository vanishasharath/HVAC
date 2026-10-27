# HVAC Leak Detection — Backend, Real AI Integration

This delivery connects your teammate's **actually trained** Isolation Forest + LSTM + Random Forest pipeline to the FastAPI backend, replacing the earlier stub adapters. All 3 model files were genuinely trained (not simulated) from the unmodified training scripts you uploaded — see section 4.

---

## 1. What changed, file by file

### 🔴 Changed

| File | What changed | Why |
|---|---|---|
| `app/schemas/sensor.py` | Raw field names: `gas_ppm`, `pressure`, `temperature`, `humidity`, `compressor_current` | Must match `RAW_COLS` in the feature engineering exactly, or values silently go to the wrong feature |
| `app/api/sensors.py` | No signature change — but now triggers the real pipeline underneath | Same endpoint, real behavior |
| `app/services/sensor_service.py` | After InfluxDB write, calls `pipeline_manager.process_reading()` then the alert engine | This is the actual integration point — every ingested reading now runs through real inference |
| `app/services/prediction_service.py`, `forecast_service.py` | Now read the pipeline manager's cached last result for a unit, instead of stub logic | `/predict` and `/forecast` are real |
| `app/services/alert_service.py` | New function `evaluate_and_create_alert_from_pipeline_result()`, new `SEVERITY_TIER_MAP` | Reconciles the RF's 4-class output (Low/Medium/High/Critical) with your report's 3-tier alert scheme (WARNING/PREDICTIVE/CRITICAL) — see section 3 |
| `app/schemas/alert.py` | Added `rf_severity`, `rf_confidence`, `anomaly_flag`, `anomaly_duration`, `lstm_prob_24hr`, `lstm_prob_48hr` | Preserves the real model's full output, not just the mapped tier |
| `app/config.py` | Added `model_dir` setting | Points at `app/ai/models/` where the real files live |
| `requirements.txt` | Added `pandas`, `numpy`, `scikit-learn`, `joblib`, `tensorflow-cpu` (all required now, not optional) | The real models need these to load and run |
| `scripts/simulate_sensor_data.py` | Baseline values now match `BASELINE` in your teammate's `generate_synthetic_data.py` | So simulated demo readings produce realistic AI transitions instead of arbitrary numbers the models weren't trained on |

### 🟢 Untouched (as requested)

`app/api/auth.py`, `app/services/auth_service.py`, `app/schemas/user.py`, `app/security/`, `app/database/mongodb.py`, `app/database/influxdb.py` — none of these needed to change for this integration.

### 🆕 Added

| File | Purpose |
|---|---|
| `app/ai/feature_engineering.py` | `StreamingFeatureEngineer` — computes the 10-feature vector one reading at a time, **numerically verified identical** to your teammate's pandas batch computation (see section 2) |
| `app/ai/real_pipeline.py` | Your teammate's `inference_pipeline.py`, copied in **unmodified** — the real `LeakDetectionPipeline` and `SensorStream` classes |
| `app/ai/pipeline_manager.py` | New — manages one `(StreamingFeatureEngineer, SensorStream)` pair per HVAC unit, since a stateless FastAPI request can't hold the 36-reading LSTM buffer or anomaly-duration counter on its own |
| `app/ai/models/*.pkl`, `*.h5` | **Real, trained model files** — see section 4 for training results |
| `app/ai/test_feature_engineering_matches_training.py` | Proves the streaming feature computation matches pandas batch to 9 decimal places |
| `ml_training/` | Your original 6 uploaded scripts, unmodified, kept for reproducibility |

---

## 2. The one thing that had to be exactly right

Your teammate's `add_derived_features()` (in `generate_synthetic_data.py`) computes rate-of-change as a **raw difference** (`diff().fillna(0)`) and rolling stats over a **30-sample window** (`rolling(window=30, min_periods=1)`) — not time-based, not normalized by elapsed seconds. My first attempt at this integration (before you uploaded the real scripts) used per-second-normalized rates and a time-based rolling window — those would have silently fed the real model numbers it was never trained on.

`app/ai/feature_engineering.py` was rewritten to reproduce the exact same computation as a stream (one reading at a time, maintaining a small buffer), and `app/ai/test_feature_engineering_matches_training.py` proves — genuinely, not asserted — that the streaming version matches the pandas batch version to 9 decimal places, on both random noise and an actual leak-drift sequence.

## 3. The severity reconciliation

Your real Random Forest outputs 4 classes: `Low`, `Medium`, `High`, `Critical`. Your report and existing alert schema use 3 tiers: `WARNING`, `PREDICTIVE`, `CRITICAL`. Rather than silently picking one, `app/services/alert_service.py` makes this explicit:

```python
SEVERITY_TIER_MAP = {
    "Low": None,        # no alert created
    "Medium": "WARNING",
    "High": "PREDICTIVE",
    "Critical": "CRITICAL",
}
```

This is a **BACKEND IMPLEMENTATION DECISION** — flag it as a deliberate reconciliation in your report/viva, not an oversight. The full RF output (`rf_severity`, `rf_confidence`) is preserved on every alert record alongside the mapped tier, so nothing from the real model's decision is lost.

## 4. Real training results (from your unmodified scripts, run in this delivery)

| Model | Result |
|---|---|
| **Isolation Forest** | Trained on 48,032 healthy samples. 2.02% false-positive rate on held-out healthy data. On the full dataset (including leaks it never saw during training): **99% accuracy**, 98% recall on leak detection |
| **LSTM** | Converged in 11 epochs (early stopping). Final validation accuracy: **98% (24hr head), 95% (48hr head)** |
| **Random Forest** | **99% accuracy** across all 4 severity classes on held-out test sequences |

These are genuinely trained models, not placeholders — verified by running your teammate's own `inference_pipeline.py` `demo()` function unmodified, which correctly walked a real critical leak sequence from `Low` → `Critical` severity exactly where the leak begins.

**Verified further**, through the actual backend code path (`sensor_service.ingest_sensor_data()`, not a shortcut): a healthy reading correctly returns `Low` (99.9% confidence); a leak-pattern reading correctly returns `Critical` (76% confidence), anomaly flag firing, rate-of-change and rolling stats all computed correctly.

## 5. What is NOT tested — read before your demo

- **No live MongoDB or InfluxDB was available in this environment.** Ingestion's InfluxDB write and the alert engine's MongoDB write were both confirmed to fail *cleanly* (proper 500, logged server-side, nothing crashes) when no database is reachable — but the actual successful write path needs your real databases running to verify.
- **The LSTM forecast (`lstm_prob_24hr`/`lstm_prob_48hr`) stays at 0.0 until 36 readings have been ingested for a given `hvac_id`** — this is real `SensorStream` behavior, not a bug. Your demo sequence needs at least 36 readings before forecast numbers become meaningful; fewer than that and `/forecast` will correctly report `forecast_ready: false`.
- **Per-HVAC state is in-memory, single-process** (documented in `pipeline_manager.py`) — resets on server restart, doesn't work correctly with multiple uvicorn workers. Fine for your demo; flagged as a production limitation, matching what your teammate's own `SensorStream` docstring already says about needing Redis in production.
- **A real WebSocket client receiving a live broadcast** — connection manager code is unchanged and was verified working in the prior delivery, not re-tested here.

## 6. Running this

```bash
python -m venv venv
venv\Scripts\Activate.ps1          # Windows
pip install -r requirements.txt    # includes tensorflow-cpu - this install takes a few minutes
copy .env.example .env
uvicorn app.main:app --reload
```

Check `/health` — it now reports `"ai_pipeline_loaded": true` if all 4 model files loaded correctly.

### Live Simulator & AI Trend Estimation:

Run the physics-informed live simulator with location-specific pressure and contextual humidity:

```bash
# Standard suction-line leak with stable humidity:
python scripts/simulate_sensor_data.py --location suction_line --humidity stable --leak-rate medium

# High-side discharge line transducer with fluctuating ambient humidity:
python scripts/simulate_sensor_data.py --location discharge_line --humidity fluctuating --leak-rate fast

# Indoor supply plenum transducer with humid monsoon context:
python scripts/simulate_sensor_data.py --location indoor_ambient_plenum --humidity humid --leak-rate slow
```

**Simulation Features:**
1. **Progressive Gas Concentration**: Progressively climbs from baseline 5.0 ppm up to critical thresholds (400+ ppm).
2. **Pressure Behavior by Sensor Location**:
   - `suction_line` (Low-side): Drops progressively from 165 down to ~105 psi as charge depletes.
   - `discharge_line` (High-side): Initial superheat/compressor strain surge (+18 psi) followed by head pressure collapse down to ~290 psi.
   - `liquid_line` (Condenser exit): Subcooling loss creates vapor bubbles and pressure flutter.
   - `indoor_ambient_plenum` (Supply duct): Atmospheric air pressure remains steady (~14.7 psi) while gas concentration climbs.
3. **Gradual Supply-Air Temperature Rise**: Models loss of cooling capacity as supply air leaving the coil rises from 7.0°C up to room temperature (≥ 22.0°C indicates cooling failure).
4. **Contextual Humidity**: Kept as an independent ambient variable (`stable`, `humid`, `dry`, `fluctuating`, `random_walk`), decoupled from the leak progression.
5. **AI Trend Estimation (ETTC)**: AI tracks elapsed time and rates of change ($d(\text{gas})/dt$, $d(T)/dt$, $d(P)/dt$) to project the Estimated Time to Critical Condition in real time.

