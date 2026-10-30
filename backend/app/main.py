from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import alerts, auth, forecasts, hvac, predictions, reports, sensors, simulator, users, websocket
from app.config import settings
from app.database.influxdb import close_influx_connection, connect_to_influx
from app.database.mongodb import close_mongo_connection, connect_to_mongo
from app.middleware.error_handler import register_exception_handlers
from app.utils.logging import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(settings.app_env)

    # Import here so the real AI pipeline loading and any errors
    # are visible during application startup.
    from app.ai.pipeline_manager import pipeline_manager

    if pipeline_manager.is_loaded:
        import logging

        logging.getLogger("startup").info(
            "Real AI pipeline loaded successfully from %s",
            pipeline_manager._models_dir,
        )
    else:
        import logging

        logging.getLogger("startup").error(
            "Real AI pipeline FAILED to load from %s - /predict, /forecast, "
            "and alert creation will error until this is fixed. Check that "
            "isolation_forest_r32.pkl, lstm_leak_forecast.h5, "
            "lstm_scaler.pkl, random_forest_severity.pkl all exist "
            "in that directory.",
            pipeline_manager._models_dir,
        )

    await connect_to_mongo()
    connect_to_influx()

    yield

    await close_mongo_connection()
    close_influx_connection()


app = FastAPI(
    title=settings.app_name,
    description=(
        "Backend for the AI-Powered Predictive Refrigerant Leak Detection "
        "and Smart HVAC Monitoring System - now running the REAL trained AI pipeline."
    ),
    version=settings.app_version,
    lifespan=lifespan,
)



# Allow the React/Vite frontend to communicate with FastAPI.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



register_exception_handlers(app)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(hvac.router)
app.include_router(sensors.router)
app.include_router(predictions.router)
app.include_router(forecasts.router)
app.include_router(alerts.router)
app.include_router(reports.router)
app.include_router(websocket.router)
app.include_router(simulator.router)


@app.get("/")
def root():
    from app.ai.pipeline_manager import pipeline_manager

    return {
        "service": "refrigerant-leak-detection-backend",
        "status": "running",
        "environment": settings.app_env,
        "ai_pipeline_loaded": pipeline_manager.is_loaded,
    }


@app.get("/health")
def health_check():
    from app.ai.pipeline_manager import pipeline_manager

    return {
        "status": "healthy",
        "environment": settings.app_env,
        "ai_pipeline_loaded": pipeline_manager.is_loaded,
    }