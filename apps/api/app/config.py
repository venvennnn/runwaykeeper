from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://runwaykeeper:runwaykeeper@localhost:5432/runwaykeeper"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:3000"
    demo_api_key: str = "rk_demo_harbor_studio"
    demo_workspace_id: str = "00000000-0000-4000-8000-000000000001"

    aws_region: str = "us-west-2"
    bedrock_model_id: str = "anthropic.claude-sonnet-4-20250514-v1:0"

    resend_api_key: str = ""
    resend_from_email: str = "RunwayKeeper <billing@example.test>"
    resend_webhook_secret: str = ""

    km_min_invoices: int = 50
    km_min_events: int = 20
    forecast_scenarios: int = 2000
    forecast_horizon_days: int = 30
    forecast_seed: int = 42

    worker_poll_seconds: float = 2.0
    job_lease_seconds: int = 60
    job_max_attempts: int = 5

    aws_builder_id: str = ""
    deployment_url: str = ""


settings = Settings()
