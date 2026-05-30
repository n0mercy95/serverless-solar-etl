"""
infrastructure/bigquery_adapter.py — Adaptador Nativo BigQuery
==============================================================
Implementa el puerto ``DataWarehouseRepository(ABC)`` utilizando
el cliente nativo de ``google-cloud-bigquery``.

Características Principales:
1. **Idempotencia por WRITE_TRUNCATE**: Cada ejecución reemplaza
   completamente la tabla con los datos del Parquet actual.
   ``WRITE_TRUNCATE`` es inherentemente idempotente: N ejecuciones
   con los mismos datos siempre producen exactamente el mismo resultado.
2. **Clusterización/Particionamiento**: Configura un ``LoadJobConfig`` con
   particionamiento temporal en ``date_time`` y agrupamiento en ``station_id``.
3. **Ejecución Asíncrona Resiliente**: Dispara el load job y aguarda su
   resultado, envolviendo todas las fallas en ``BigQueryConnectionError``.
4. **Validación Post-Carga**: Verifica que las filas cargadas coincidan con
   lo esperado y emite advertencia si detecta inconsistencias.

Referencia PRD §4 y §6 (Tarea 3.2).
"""

from __future__ import annotations

import logging
import uuid

from app.application.data_warehouse_port import DataWarehouseRepository
from app.domain.constants import STATION_COLUMN, TEMPORAL_COLUMN
from app.domain.exceptions import BigQueryConnectionError

logger = logging.getLogger(__name__)


class BigQueryAdapter(DataWarehouseRepository):
    """Adaptador para inyectar datos Parquet en Google BigQuery.

    Parameters
    ----------
    project_id : str
        ID del proyecto GCP donde reside BigQuery.
    dataset_id : str
        ID del Dataset donde se creará o actualizará la tabla.
    table_id : str
        ID de la Tabla objetivo (ej. ``pvod_metrics``).
    bucket_name : str
        Nombre del bucket de GCS (mantenido por compatibilidad de interfaz).
    credentials_path : str | None, optional
        Ruta al archivo JSON de credenciales de servicio (si aplica).
    """

    def __init__(
        self,
        project_id: str,
        dataset_id: str,
        table_id: str,
        bucket_name: str,
        *,
        credentials_path: str | None = None,
    ) -> None:
        self._project_id = project_id
        self._dataset_id = dataset_id
        self._table_id = table_id
        self._bucket_name = bucket_name
        self._credentials_path = credentials_path

        self._table_ref = f"{project_id}.{dataset_id}.{table_id}"

    # ── Contrato ABC ──────────────────────────────────────────────────

    def load_dataframe_idempotent(self, gcs_uri: str) -> str:
        """Carga masiva desde GCS a BigQuery con WRITE_TRUNCATE.

        Cada ejecución reemplaza completamente la tabla destino con los
        registros del Parquet en GCS.  ``WRITE_TRUNCATE`` garantiza
        idempotencia: no importa cuántas veces se ejecute, la tabla
        siempre queda con exactamente los registros del Parquet actual
        (cero duplicados).

        Parameters
        ----------
        gcs_uri : str
            URI completa (``gs://...``) del archivo Parquet en la Capa Oro.

        Returns
        -------
        str
            El identificador del Job generado (ej. ``pvod_load_<uuid>``).

        Raises
        ------
        BigQueryConnectionError
            Si no es posible contactar la API de BQ o si el Load Job falla.
        """
        # Evitamos importar estas librerías en top-level si no es necesario
        try:
            from google.cloud import bigquery
        except ImportError as exc:
            raise BigQueryConnectionError(
                f"Librerías GCP no instaladas o no detectadas: {exc}"
            ) from exc

        logger.info(
            "Iniciando flujo BigQuery Load (WRITE_TRUNCATE)",
            extra={
                "attributes": {
                    "source_uri": gcs_uri,
                    "target_table": self._table_ref,
                },
            },
        )

        try:
            # 1. Generar Job ID único (UUID garantiza que cada ejecución
            #    siempre crea un Job nuevo — WRITE_TRUNCATE provee la
            #    idempotencia, no el Job ID).
            job_id = f"pvod_load_{uuid.uuid4().hex}"

            # 2. Configurar el LoadJob (Particiones, Clústeres, Modo Parquet)
            job_config = self._build_load_job_config(bigquery)

            # 3. Instanciar cliente y lanzar Load Job
            bq_client = (
                bigquery.Client.from_service_account_json(self._credentials_path)
                if self._credentials_path
                else bigquery.Client(project=self._project_id)
            )

            logger.info(
                "Lanzando Load Job en BigQuery (TRUNCATE + reemplazo total)",
                extra={
                    "attributes": {
                        "job_id": job_id,
                        "write_disposition": "WRITE_TRUNCATE",
                        "clustering": [STATION_COLUMN],
                        "partitioning": TEMPORAL_COLUMN,
                    },
                },
            )

            # API Asíncrona — Devuelve un objeto LoadJob inmediatamente
            load_job = bq_client.load_table_from_uri(
                source_uris=gcs_uri,
                destination=self._table_ref,
                job_id=job_id,
                job_config=job_config,
            )

            # Aguardar resolución (bloqueante aquí)
            load_job.result()

            rows_loaded = getattr(load_job, "output_rows", 0)

            logger.info(
                "BigQuery Load Job completado exitosamente (tabla reemplazada)",
                extra={
                    "attributes": {
                        "job_id": load_job.job_id,
                        "rows_loaded": rows_loaded,
                        "state": load_job.state,
                    },
                },
            )

            # 4. Validación post-carga: verificar conteo real en la tabla
            self._validate_row_count(bq_client, rows_loaded)

            return load_job.job_id

        except BigQueryConnectionError:
            raise
        except Exception as exc:
            raise BigQueryConnectionError(
                f"Fallo durante ejecución transaccional a BigQuery: {exc}"
            ) from exc

    # ── Métodos Internos ──────────────────────────────────────────────

    def _validate_row_count(self, bq_client: object, expected_rows: int) -> None:
        """Valida que el conteo de filas en la tabla coincida con lo cargado.

        Emite un WARNING si el conteo no coincide, lo que indicaría una
        posible duplicación o corrupción de datos.

        Parameters
        ----------
        bq_client : bigquery.Client
            Cliente BigQuery ya instanciado.
        expected_rows : int
            Número de filas que el Load Job reportó haber cargado.
        """
        try:
            table = bq_client.get_table(self._table_ref)  # type: ignore[union-attr]
            actual_rows = table.num_rows

            if actual_rows != expected_rows and expected_rows > 0:
                logger.warning(
                    "⚠️ ALERTA DE INTEGRIDAD: El conteo de filas en BigQuery "
                    "no coincide con las filas cargadas. Posible duplicación detectada.",
                    extra={
                        "attributes": {
                            "expected_rows": expected_rows,
                            "actual_rows": actual_rows,
                            "table": self._table_ref,
                        },
                    },
                )
            else:
                logger.info(
                    "✓ Validación post-carga exitosa: conteo de filas correcto",
                    extra={
                        "attributes": {
                            "rows": actual_rows,
                            "table": self._table_ref,
                        },
                    },
                )
        except Exception as exc:
            logger.warning(
                "No se pudo validar el conteo de filas post-carga: %s", exc
            )

    def _build_load_job_config(self, bq_module: object) -> object:
        """Construye y retorna el ``LoadJobConfig`` con clustering y particionamiento.

        Parquet provee su propio esquema en el backend, no requerimos
        definir un SchemaField explícito a menos que BQ lo pida (rara vez).
        """
        job_config = bq_module.LoadJobConfig()  # type: ignore[union-attr]
        job_config.source_format = bq_module.SourceFormat.PARQUET  # type: ignore[union-attr]

        # WRITE_TRUNCATE: Cada ejecución REEMPLAZA la tabla completa.
        # Esto es inherentemente idempotente: N ejecuciones = mismo resultado.
        # NO se acumulan duplicados bajo ninguna circunstancia.
        job_config.write_disposition = bq_module.WriteDisposition.WRITE_TRUNCATE  # type: ignore[union-attr]

        # PRD §4: Particionamiento y Clustering
        job_config.time_partitioning = bq_module.TimePartitioning(  # type: ignore[union-attr]
            type_=bq_module.TimePartitioningType.DAY,  # type: ignore[union-attr]
            field=TEMPORAL_COLUMN,
        )
        job_config.clustering_fields = [STATION_COLUMN]

        return job_config
