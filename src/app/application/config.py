"""
application/config.py — Configuración Centralizada del Pipeline
================================================================
Usa ``pydantic-settings`` para leer y validar variables de entorno
de forma tipada y determinista.  Las variables se cargan desde el
archivo ``.env`` en desarrollo y desde variables de entorno inyectadas
por Cloud Run / Secret Manager en producción.
"""

from __future__ import annotations

from pydantic import HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración global del ETL Solar, validada en tiempo de arranque.

    Cada campo mapea 1:1 con una variable del ``.env`` / ``.env.example``.
    Los nombres se convierten automáticamente a mayúsculas (case-insensitive).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Google Cloud Platform ────────────────────────────────────
    gcp_project_id: str
    google_application_credentials: str

    # ── BigQuery ─────────────────────────────────────────────────
    bq_dataset_id: str
    bq_table_id: str
    bq_max_bytes_billed: int = 104857600  # 100 MB default quota

    # ── Cloud Storage (Gold Layer Buffer) ────────────────────────
    gcs_bucket_name: str

    # ── Data Sources (Ingesta) ───────────────────────────────────
    github_raw_url: HttpUrl
    scidb_fallback_url: HttpUrl

    # ── Application ──────────────────────────────────────────────
    environment: str = "development"
    log_level: str = "INFO"
