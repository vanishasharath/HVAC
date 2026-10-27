# AI-Powered Predictive Refrigerant Leak Detection and Smart HVAC Monitoring System

## Overview

The **AI-Powered Predictive Refrigerant Leak Detection and Smart HVAC Monitoring System** is a full-stack application designed to monitor HVAC operating conditions, detect potential refrigerant leaks, predict future leak risks, and generate alerts based on the severity of detected anomalies.

The system integrates machine learning models with a FastAPI backend, a React-based monitoring dashboard, time-series data storage, and sensor firmware to support real-time monitoring and predictive maintenance.

The project combines anomaly detection, time-series forecasting, and severity classification to help identify abnormal HVAC operating conditions before they develop into more serious failures.

## Key Features

- **Sensor Monitoring:** Processes HVAC sensor readings, including gas concentration, pressure, temperature, humidity, and compressor current.
- **AI-Based Anomaly Detection:** Uses an Isolation Forest model to identify abnormal sensor patterns.
- **Predictive Leak Forecasting:** Uses an LSTM model to estimate leak probabilities for the next 24 and 48 hours.
- **Leak Severity Classification:** Uses a Random Forest classifier to categorize leak severity as Low, Medium, High, or Critical.
- **Intelligent Alert Generation:** Maps model severity outputs to the application's alert levels and creates alerts for actionable risk conditions.
- **Live Data Simulation:** Supports simulated sensor readings for testing the monitoring and prediction pipeline.
- **HVAC Monitoring Dashboard:** Provides a React-based frontend for monitoring system data and interacting with backend services.
- **Time-Series Data Storage:** Integrates InfluxDB for sensor data and MongoDB for application records.
- **REST API:** Uses FastAPI to expose endpoints for sensor ingestion, predictions, forecasts, alerts, reports, authentication, and HVAC management.
- **WebSocket Support:** Includes backend infrastructure for live updates.
- **Reporting:** Includes report-generation functionality for presenting monitoring information.

## System Architecture

The application follows a modular architecture consisting of the sensor layer, backend services, AI inference pipeline, databases, and frontend dashboard.

1. **Sensor Layer:** Collects or simulates HVAC operating measurements.
2. **Backend API:** Receives sensor readings through FastAPI endpoints.
3. **Feature Engineering:** Converts raw readings into the feature representation expected by the trained models.
4. **AI Pipeline:** Performs anomaly detection, forecasting, and severity classification.
5. **Alert Engine:** Evaluates prediction results and generates alerts according to the configured severity mapping.
6. **Database Layer:** Stores time-series measurements and application data using InfluxDB and MongoDB.
7. **Frontend Dashboard:** Displays monitoring information and communicates with the backend.

### Machine Learning Pipeline

| Model | Purpose | Output |
|---|---|---|
| Isolation Forest | Detects anomalous sensor behavior | Anomaly score and detection flag |
| LSTM | Forecasts future leak probability | 24-hour and 48-hour probabilities |
| Random Forest | Classifies leak severity | Low, Medium, High, or Critical |

The models are integrated into a streaming inference pipeline that maintains per-HVAC feature history and sensor state.

### Alert Severity Mapping

The backend maps the four Random Forest severity classes to the application's three alert tiers:

| Model Classification | Application Alert Tier |
|---|---|
| Low | No alert |
| Medium | WARNING |
| High | PREDICTIVE |
| Critical | CRITICAL |

The original model classification and associated prediction information are retained in alert records.

## Technology Stack

### Frontend
- React
- Vite
- JavaScript
- Tailwind CSS
- Recharts
- React Router

### Backend
- Python
- FastAPI
- Uvicorn
- Pydantic
- WebSockets

### Artificial Intelligence and Machine Learning
- TensorFlow / Keras
- Scikit-learn
- NumPy
- Pandas
- Joblib

### Databases
- InfluxDB — time-series sensor data
- MongoDB — application records and related data

### Hardware and Firmware
- ESP32-compatible firmware
- Arduino framework
- Sensor integration through the configured hardware interfaces

## Project Structure

```text
HVAC/
├── backend/
│   ├── app/
│   │   ├── ai/
│   │   │   ├── models/
│   │   │   ├── feature_engineering.py
│   │   │   ├── pipeline_manager.py
│   │   │   ├── real_pipeline.py
│   │   │   └── trend_estimator.py
│   │   ├── api/
│   │   ├── database/
│   │   ├── middleware/
│   │   ├── schemas/
│   │   ├── security/
│   │   ├── services/
│   │   ├── utils/
│   │   └── main.py
│   ├── ml_training/
│   ├── scripts/
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   ├── public/
│   ├── package.json
│   └── vite.config.js
├── firmware/
│   └── sketch_oct7a.ino
├── package.json
└── README.md
```

## Prerequisites

Install the following before running the application:

- Python 3.11 recommended for the AI backend environment
- Node.js and npm
- MongoDB
- InfluxDB
- Git

The project uses pinned Python dependencies, including TensorFlow. Compatible Python, operating system, and package versions are important for loading the saved machine learning models.

## Installation and Setup

### 1. Clone the Repository

```bash
git clone <YOUR_REPOSITORY_URL>
cd HVAC
```

Replace `<YOUR_REPOSITORY_URL>` with your Git repository URL.

### 2. Set Up the Backend

Open a terminal in the repository root:

```bash
cd backend
python3.11 -m venv .venv
```

Activate the environment.

**macOS / Linux**

```bash
source .venv/bin/activate
```

**Windows PowerShell**

```powershell
.\.venv\Scripts\Activate.ps1
```

Install the dependencies:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Create a `.env` file inside the `backend` directory using `.env.example` as the template.

Configure the following values according to your local environment:

```env
APP_NAME="Refrigerant Leak Detection API"
APP_ENV=development
APP_VERSION=0.1.0

MONGODB_URL=mongodb://localhost:27017
MONGODB_DB_NAME=hvac_leak_detection

INFLUXDB_URL=http://localhost:8086
INFLUXDB_TOKEN=your-influxdb-token
INFLUXDB_ORG=your-influxdb-organization
INFLUXDB_BUCKET=hvac_sensor_data

JWT_SECRET_KEY=replace_with_a_secure_random_secret
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60

INGESTION_API_KEY=replace_with_a_unique_ingestion_key

MODEL_DIR=app/ai/models
```

Use valid database credentials, organization details, bucket names, and secure secrets. Do not commit the `.env` file to version control.

### 4. Verify the AI Model Files

The following trained model files should be present inside `backend/app/ai/models/`:

```text
isolation_forest_r32.pkl
lstm_leak_forecast.h5
lstm_scaler.pkl
random_forest_severity.pkl
```

The backend loads these files when the application starts.

**Important:** The saved models and feature engineering must remain compatible with the installed machine learning libraries and the feature representation used during training.

### 5. Start the Backend

From the `backend` directory, with the virtual environment activated:

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Verify that the service is running:

- API root: http://127.0.0.1:8000/
- Health check: http://127.0.0.1:8000/health
- Interactive API documentation: http://127.0.0.1:8000/docs

The health endpoint reports whether the AI pipeline loaded successfully. A healthy API response alone does not guarantee that database writes or every application feature is working.

### 6. Start the Frontend

Open a separate terminal:

```bash
cd frontend
npm install
npm run dev
```

Open the local URL printed by Vite, typically:

http://localhost:5173/

Ensure that the frontend is configured to communicate with the backend API.

### 7. Start the Databases

Start MongoDB and InfluxDB using your local installation or configured services. Ensure that the connection settings, InfluxDB organization, bucket, and token match the backend environment variables.

Database connectivity is required to verify the complete persistence and alert-generation workflow.

## Running the Machine Learning Pipeline

The backend integrates the saved machine learning models through the pipeline manager.

For each HVAC unit, the pipeline maintains streaming feature history and processes incoming readings through the inference stages.

The general processing flow is:

```text
Sensor Readings
      |
      v
Feature Engineering
      |
      v
Isolation Forest
      |
      v
LSTM Forecasting
      |
      v
Random Forest Classification
      |
      v
Alert Evaluation
      |
      v
Dashboard and Data Storage
```

The LSTM forecast requires a sufficient history of sensor readings. In the current implementation, the forecast becomes ready after 36 readings have been collected for a given HVAC unit.

## Testing

The backend includes tests for important AI pipeline components.

From the `backend` directory, run:

```bash
python -m pytest -v
```

To run the feature-engineering consistency tests specifically:

```bash
python -m pytest app/ai/test_feature_engineering_matches_training.py -v
```

To test the live simulator pipeline:

```bash
python -m pytest app/ai/test_live_simulator_pipeline.py -v
```

To test trend estimation:

```bash
python -m pytest app/ai/test_trend_estimator.py -v
```

These tests cover selected pipeline behaviors. Passing unit tests does not by itself establish successful end-to-end operation with live hardware and databases.

## Current Limitations

- The system's predictive performance depends on the quality and representativeness of the training data.
- Forecasting requires sufficient sensor history for each HVAC unit.
- The current per-unit streaming state is maintained in memory and is reset when the backend restarts.
- Multi-worker deployment requires a shared state-management solution.
- Database availability and configuration are necessary for validating persistent data storage and alert records.
- Live hardware integration and real-world leak testing require separate validation with physical sensors and HVAC equipment.

## Future Enhancements

- Validate the models using real-world refrigerant leak measurements.
- Expand the training dataset to include varied operating conditions and leak scenarios.
- Improve multi-unit scalability through persistent shared streaming state.
- Add monitoring, model-performance tracking, and automated retraining.
- Strengthen authentication, API security, and production deployment configuration.
- Conduct end-to-end validation across physical sensors, the backend, databases, and dashboard.

## Conclusion

This project integrates machine learning and full-stack development to support predictive refrigerant leak monitoring in HVAC systems. By combining anomaly detection, future leak probability estimation, severity classification, and alert generation, the system provides a foundation for proactive HVAC maintenance and improved operational monitoring.

**Note:** AI predictions are decision-support outputs and should not be treated as a substitute for physical inspection, calibrated leak detection equipment, or appropriate safety procedures.
