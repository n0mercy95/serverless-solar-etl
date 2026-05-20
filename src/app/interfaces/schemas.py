"""
interfaces/schemas.py — Modelos Pydantic para la API
======================================================
Define los contratos de entrada y salida para los endpoints
del microservicio, asegurando tipado estricto y validación.
"""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field


class MetricsQueryRequest(BaseModel):
    """Solicitud para consultar métricas agregadas."""

    start_date: datetime = Field(
        ...,
        description="Fecha y hora de inicio para el filtrado temporal (LST).",
    )
    end_date: datetime = Field(
        ...,
        description="Fecha y hora de fin para el filtrado temporal (LST).",
    )
    dry_run: bool = Field(
        default=False,
        description="Si es True, devuelve el costo estimado en bytes sin ejecutar la consulta real.",
    )


class StationPowerAvg(BaseModel):
    """Métrica agregada promedio por estación."""

    station_id: int = Field(..., description="ID de la estación fotovoltaica (0-9).")
    avg_power: float | None = Field(..., description="Promedio de potencia generada (kW).")


class MetricsQueryResponse(BaseModel):
    """Respuesta con los resultados reales de la consulta."""

    results: list[StationPowerAvg]
    total_rows: int
    bytes_processed: int | None = None


class DryRunResponse(BaseModel):
    """Respuesta del costo estimado (Dry Run)."""

    estimated_bytes_processed: int
    message: str = "Estimación completada exitosamente sin cargos a facturación."


class PipelineRunResponse(BaseModel):
    """Respuesta de una ejecución del pipeline ETL completo.

    Contiene métricas detalladas de cada paso ejecutado, URIs de
    artefactos generados y el identificador del Load Job de BigQuery.
    """

    status: str = Field(
        ..., description="Estado de la ejecución: 'success' o 'failed'."
    )
    records_processed: int = Field(
        ..., description="Cantidad de registros procesados y cargados."
    )
    gcs_uri: str = Field(
        ..., description="URI del Parquet exportado a la Capa Oro (gs://...)."
    )
    bigquery_job_id: str = Field(
        ..., description="Identificador determinista (MD5) del Load Job de BigQuery."
    )
    duration_seconds: float = Field(
        ..., description="Duración total de la ejecución en segundos."
    )
    started_at: str = Field(
        ..., description="Timestamp ISO 8601 UTC del inicio."
    )
    completed_at: str = Field(
        ..., description="Timestamp ISO 8601 UTC del fin."
    )
    steps_completed: list[str] = Field(
        default_factory=list,
        description="Lista de pasos completados: extraction, transformation, cleaning, gold_export, bigquery_load.",
    )
