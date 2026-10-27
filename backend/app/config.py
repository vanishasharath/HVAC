from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Refrigerant Leak Detection API"
    app_env: str = "development"
    app_version: str = "0.1.0"

    mongodb_url: str = "mongodb://localhost:27017"
    mongodb_db_name: str = "hvac_leak_detection"

    influxdb_url: str = "http://localhost:8086"
    influxdb_token: str = "placeholder-token"
    influxdb_org: str = "placeholder-org"
    influxdb_bucket: str = "hvac_sensor_data"

    jwt_secret_key: str = "dev-only-secret-change-before-real-use"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60

    ingestion_api_key: str = "dev-only-ingestion-key"

    # ---- AI model directory - now points at the REAL trained models ----
    model_dir: str = "app/ai/models"

    # ---- Alert severity mapping (RF outputs Low/Medium/High/Critical;
    # report terminology uses WARNING/PREDICTIVE/CRITICAL - see alert_service.py) ----

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        protected_namespaces=(),
    )


settings = Settings()
