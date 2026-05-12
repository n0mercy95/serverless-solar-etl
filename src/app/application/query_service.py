"""
application/query_service.py — Servicio de Consultas a BigQuery
===============================================================
Encapsula la lógica de negocio para interactuar con la Capa Serving 
(Data Warehouse). Protege contra inyecciones SQL utilizando consultas
puramente parametrizadas y respeta la cuota de BigQuery definida en 
la configuración para operar en el nivel gratuito.
"""

from __future__ import annotations

import logging
from datetime import datetime

from google.cloud import bigquery

from app.application.config import Settings
from app.domain.exceptions import BigQueryConnectionError
from app.interfaces.schemas import (
    DryRunResponse,
    MetricsQueryRequest,
    MetricsQueryResponse,
    StationPowerAvg,
)

logger = logging.getLogger(__name__)


class BigQueryQueryService:
    """Servicio de consultas analíticas para el dataset PVOD.

    Parameters
    ----------
    bq_client : bigquery.Client
        Cliente BigQuery (inyectado desde FastAPI state para reciclaje).
    settings : Settings
        Configuración global (inlcuye los límites de bytes_billed).
    """

    def __init__(self, bq_client: bigquery.Client, settings: Settings) -> None:
        self._bq_client = bq_client
        self._settings = settings

        # Referencia completa de la tabla
        self._table_ref = f"{settings.gcp_project_id}.{settings.bq_dataset_id}.{settings.bq_table_id}"

    def get_aggregated_metrics(
        self, request: MetricsQueryRequest
    ) -> MetricsQueryResponse | DryRunResponse:
        """Calcula el promedio de potencia por estación en un rango temporal.
        
        Soporta modo 'dry run' para estimar costos sin facturación, y aplica
        un límite estricto de bytes_billed configurado globalmente.
        """
        # 1. Consulta SQL puramente parametrizada (prevención inyección SQL)
        query = f"""
            SELECT
                station_id,
                AVG(power) as avg_power
            FROM `{self._table_ref}`
            WHERE date_time >= @start_date AND date_time <= @end_date
            GROUP BY station_id
            ORDER BY station_id ASC
        """

        # 2. Inyección segura de parámetros escalares
        query_params = [
            bigquery.ScalarQueryParameter("start_date", "DATETIME", request.start_date),
            bigquery.ScalarQueryParameter("end_date", "DATETIME", request.end_date),
        ]

        # 3. Configuración estricta del Job (Dry Run y Control de Costos)
        # El límite previene escaneos completos masivos (full table scans).
        job_config = bigquery.QueryJobConfig(
            query_parameters=query_params,
            dry_run=request.dry_run,
            use_query_cache=not request.dry_run,  # Evita usar cache si es dry_run
            maximum_bytes_billed=self._settings.bq_max_bytes_billed,
        )

        logger.info(
            "Iniciando consulta de métricas agregadas (Dry Run=%s)",
            request.dry_run,
            extra={
                "attributes": {
                    "start_date": str(request.start_date),
                    "end_date": str(request.end_date),
                    "table_ref": self._table_ref,
                }
            },
        )

        try:
            query_job = self._bq_client.query(query, job_config=job_config)

            # 4. Manejo del flujo 'Dry Run' (retorno inmediato sin data)
            if request.dry_run:
                return DryRunResponse(
                    estimated_bytes_processed=query_job.total_bytes_processed or 0
                )

            # 5. Ejecución real y extracción de resultados
            rows = query_job.result()  # Bloqueante
            
            results: list[StationPowerAvg] = []
            for row in rows:
                results.append(
                    StationPowerAvg(
                        station_id=row.station_id,
                        avg_power=row.avg_power,
                    )
                )

            return MetricsQueryResponse(
                results=results,
                total_rows=query_job.result().total_rows,
                bytes_processed=query_job.total_bytes_processed,
            )

        except Exception as exc:
            logger.error(f"Fallo en la consulta BigQuery: {exc}")
            raise BigQueryConnectionError(f"Error procesando la consulta: {exc}") from exc
