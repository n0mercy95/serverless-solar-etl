"""
main.py — Entry Point del Microservicio PVOD Solar ETL
=======================================================
Inicializa el sistema de logging estructurado JSON (Google Cloud Logging)
y el servidor FastAPI.  La configuración de logging se ejecuta ANTES de
cualquier importación que use ``logging.getLogger(__name__)`` para
garantizar que todos los módulos hereden el handler estructurado.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from google.cloud import bigquery

from app.application.config import Settings
from app.infrastructure.cloud_logging import setup_cloud_logging
from app.interfaces.api import router as api_router

# ── Inicialización de Configuración y Logging ────────────────────────
settings = Settings()

setup_cloud_logging(
    log_level=settings.log_level,
    gcp_project_id=settings.gcp_project_id,
    environment=settings.environment,
)

logger = logging.getLogger(__name__)

# ── FastAPI Application ──────────────────────────────────────────────
app = FastAPI(
    title="PVOD Serverless Solar ETL API",
    description="API for accessing aggregated metrics from the Photovoltaic Power Output Dataset",
    version="1.0.0",
)


@app.on_event("startup")
async def on_startup() -> None:
    """Log de arranque del servicio con métricas estructuradas."""
    logger.info(
        "PVOD Solar ETL API iniciada",
        extra={
            "attributes": {
                "environment": settings.environment,
                "log_level": settings.log_level,
                "gcp_project_id": settings.gcp_project_id,
            },
        },
    )
    
    # Inicializar cliente BigQuery para reciclar conexiones
    try:
        if settings.google_application_credentials:
            app.state.bq_client = bigquery.Client.from_service_account_json(
                settings.google_application_credentials
            )
        else:
            app.state.bq_client = bigquery.Client(project=settings.gcp_project_id)
        logger.info("Cliente BigQuery inicializado exitosamente en app.state")
    except Exception as exc:
        logger.error(f"Fallo al inicializar cliente BigQuery: {exc}")

app.include_router(api_router)


@app.get("/")
async def root():
    logger.info("Root endpoint called.")
    return {"message": "PVOD Solar ETL API is running"}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}

