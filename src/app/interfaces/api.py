"""
interfaces/api.py — FastAPI Router para Métricas PVOD
======================================================
Define los endpoints de la API expuestos a los consumidores finales.
"""

from __future__ import annotations

import logging
from typing import Union

from fastapi import APIRouter, Depends, HTTPException
from google.cloud import bigquery

from app.application.config import Settings
from app.application.query_service import BigQueryQueryService
from app.domain.exceptions import BigQueryConnectionError
from app.interfaces.dependencies import get_bq_client
from app.interfaces.schemas import (
    DryRunResponse,
    MetricsQueryRequest,
    MetricsQueryResponse,
)

logger = logging.getLogger(__name__)

# Dependencia local de configuración
def get_settings() -> Settings:
    return Settings()

router = APIRouter(prefix="/api/v1/metrics", tags=["metrics"])


@router.post(
    "/aggregate",
    response_model=Union[MetricsQueryResponse, DryRunResponse],
    summary="Consultar promedio de potencia por estación",
    description="Devuelve el promedio de potencia agrupado por 'station_id' en un rango de fechas. "
                "Soporta modo 'dry_run' para estimación de costos BQ.",
)
async def get_aggregate_metrics(
    request: MetricsQueryRequest,
    bq_client: bigquery.Client = Depends(get_bq_client),
    settings: Settings = Depends(get_settings),
):
    """Manejador para consultar las métricas analíticas agregadas."""
    service = BigQueryQueryService(bq_client=bq_client, settings=settings)
    
    try:
        response = service.get_aggregated_metrics(request=request)
        return response
    except BigQueryConnectionError as exc:
        logger.error("Error de BigQuery detectado en router", exc_info=exc)
        raise HTTPException(
            status_code=500,
            detail=f"Fallo en la ejecución de la consulta a BigQuery: {exc}"
        ) from exc
    except Exception as exc:
        logger.error("Error inesperado en router", exc_info=exc)
        raise HTTPException(status_code=500, detail="Error interno del servidor") from exc
