"""
application/config.py — Configuración Centralizada del Pipeline
================================================================
Usa ``pydantic-settings`` para leer y validar variables de entorno
de forma tipada y determinista.  Las variables se cargan desde el
archivo ``.env`` en desarrollo y desde variables de entorno inyectadas
por Cloud Run / Secret Manager en producción.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import HttpUrl, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Raíz del proyecto: config.py → application/ → app/ → src/ → project root
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Configuración global del ETL Solar, validada en tiempo de arranque.

    Cada campo mapea 1:1 con una variable del ``.env`` / ``.env.example``.
    Los nombres se convierten automáticamente a mayúsculas (case-insensitive).
    """

    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Google Cloud Platform ────────────────────────────────────
    gcp_project_id: str
    google_application_credentials: str | None = None

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

    # ── Resolución de rutas para desarrollo local ────────────────
    @model_validator(mode="after")
    def _resolve_credentials_path(self) -> Settings:
        """Remapea la ruta de credenciales del contenedor Docker a la ruta
        local equivalente cuando se ejecuta fuera del contenedor.

        En Docker el Dockerfile copia ``src/`` → ``/app/``, entonces
        ``/app/credentials/credentials.json`` (contenedor) equivale a
        ``<PROJECT_ROOT>/src/app/credentials/credentials.json`` (local).
        """
        import os

        cred = self.google_application_credentials
        if cred is None:
            # Si no hay credenciales configuradas en el entorno ni en el .env,
            # no hacemos nada para que ADC use el servidor de metadatos o WIF.
            return self

        cred_path = Path(cred)
        if cred_path.exists():
            # La ruta ya es válida (ej. dentro del contenedor Docker o ruta absoluta)
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(cred_path.resolve())
            return self

        # Intentar resolver en entorno local: /app/X -> <PROJECT_ROOT>/src/app/X
        if cred_path.parts[:2] == ("/", "app"):
            local_path = _PROJECT_ROOT / "src" / "app" / Path(*cred_path.parts[2:])
            if local_path.exists():
                self.google_application_credentials = str(local_path)
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(local_path.resolve())
                return self

        # Si el archivo no existe en el disco, eliminamos la variable de os.environ
        # para que la biblioteca google-auth no intente leer un path inválido y falle.
        if "GOOGLE_APPLICATION_CREDENTIALS" in os.environ:
            del os.environ["GOOGLE_APPLICATION_CREDENTIALS"]

        return self


