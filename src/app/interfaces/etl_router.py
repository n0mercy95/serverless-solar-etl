"""
interfaces/etl_router.py — Router FastAPI para Ejecución del Pipeline ETL
==========================================================================
Expone el endpoint ``POST /api/v1/etl/run`` que Cloud Scheduler o
Cloud Tasks pueden invocar para disparar el pipeline ETL completo.

Referencia PRD §2:
  Orquestación: Cloud Scheduler o Cloud Tasks para la invocación
  asíncrona y orquestación de la carga del pipeline ETL.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.application.config import Settings
from app.application.pipeline import PipelineResult, build_pipeline
from app.domain.exceptions import SolarETLError
from app.interfaces.schemas import PipelineRunResponse

logger = logging.getLogger(__name__)


def get_settings() -> Settings:
    """Dependencia local de configuración."""
    return Settings()


router = APIRouter(prefix="/api/v1/etl", tags=["etl"])


@router.post(
    "/run",
    response_model=PipelineRunResponse,
    summary="Ejecutar el pipeline ETL completo",
    description=(
        "Dispara la ejecución secuencial del pipeline ETL Solar PVOD: "
        "Extracción → Transformación → Limpieza → Export Parquet/GCS → BigQuery. "
        "Diseñado para ser invocado por Cloud Scheduler o Cloud Tasks."
    ),
)
async def run_etl_pipeline(
    settings: Settings = Depends(get_settings),
) -> PipelineRunResponse:
    """Ejecuta el pipeline ETL completo y retorna el resultado.

    Este endpoint es **idempotente** gracias al job_id determinista
    de BigQuery: si se invoca dos veces con los mismos datos, la
    segunda ejecución no duplicará registros.
    """
    logger.info(
        "Solicitud de ejecución del pipeline ETL recibida",
        extra={
            "attributes": {"environment": settings.environment},
        },
    )

    try:
        pipeline = build_pipeline(settings)
        result: PipelineResult = pipeline.execute()

        return PipelineRunResponse(
            status="success",
            records_processed=result.records_processed,
            gcs_uri=result.gcs_uri,
            bigquery_job_id=result.bigquery_job_id,
            duration_seconds=result.duration_seconds,
            started_at=result.started_at,
            completed_at=result.completed_at,
            steps_completed=result.steps_completed,
        )

    except SolarETLError as exc:
        logger.error(
            "Pipeline ETL falló con error del dominio",
            exc_info=exc,
            extra={
                "attributes": {
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            },
        )
        raise HTTPException(
            status_code=500,
            detail=f"Pipeline ETL falló: [{type(exc).__name__}] {exc}",
        ) from exc

    except Exception as exc:
        logger.error(
            "Pipeline ETL falló con error inesperado",
            exc_info=exc,
        )
        raise HTTPException(
            status_code=500,
            detail="Error interno inesperado durante la ejecución del pipeline ETL.",
        ) from exc
