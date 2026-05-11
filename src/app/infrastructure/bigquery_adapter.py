"""
infrastructure/bigquery_adapter.py — Adaptador Nativo BigQuery
==============================================================
Implementa el puerto ``DataWarehouseRepository(ABC)`` utilizando
el cliente nativo de ``google-cloud-bigquery``.

Características Principales:
1. **Idempotencia Transaccional**: Extrae el MD5 nativo del blob Parquet en
   GCS y construye un ``job_id`` estricto (MD5 compuesto).
2. **Clusterización/Particionamiento**: Configura un ``LoadJobConfig`` con
   particionamiento temporal en ``date_time`` y agrupamiento en ``station_id``.
3. **Ejecución Asíncrona Resiliente**: Dispara el load job y aguarda su
   resultado, envolviendo todas las fallas en ``BigQueryConnectionError``.

Referencia PRD §4 y §6 (Tarea 3.2).
"""

from __future__ import annotations

import hashlib
import logging

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
        Nombre del bucket de GCS usado para resolver el blob MD5.
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
        """Inicia y espera la carga masiva idempotente desde GCS a BigQuery.

        El ``job_id`` se calcula determinísticamente usando la URI origen,
        las coordenadas destino y el MD5 nativo del blob almacenado. Esto
        garantiza que reintentos con la misma matriz no generen duplicación.

        Parameters
        ----------
        gcs_uri : str
            URI completa (``gs://...``) del archivo Parquet en la Capa Oro.

        Returns
        -------
        str
            El identificador del Job generado (ej. ``pvod_load_1a2b...``).

        Raises
        ------
        BigQueryConnectionError
            Si no es posible calcular el MD5 del blob, contactar la API
            de BQ, o si el Load Job falla.
        """
        # Evitamos importar estas librerías en top-level si no es necesario
        try:
            from google.cloud import bigquery, storage
        except ImportError as exc:
            raise BigQueryConnectionError(
                f"Librerías GCP no instaladas o no detectadas: {exc}"
            ) from exc

        logger.info(
            "Iniciando flujo transaccional BigQuery Load",
            extra={
                "attributes": {
                    "source_uri": gcs_uri,
                    "target_table": self._table_ref,
                },
            },
        )

        try:
            # 1. Resolver el MD5 Hash del Blob nativo (evita descargar archivo)
            blob_md5 = self._get_blob_md5_hash(gcs_uri, storage)

            # 2. Construir el Job ID determinista (PRD §4)
            job_id = self._generate_deterministic_job_id(gcs_uri, blob_md5)

            # 3. Configurar el LoadJob (Particiones, Clústeres, Modo Parquet)
            job_config = self._build_load_job_config(bigquery)

            # 4. Instanciar cliente y lanzar Load Job
            bq_client = (
                bigquery.Client.from_service_account_json(self._credentials_path)
                if self._credentials_path
                else bigquery.Client(project=self._project_id)
            )

            logger.info(
                "Lanzando Load Job Asíncrono en BigQuery",
                extra={
                    "attributes": {
                        "job_id": job_id,
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

            # Aguardar resolución (bloqueante aquí, pero el servidor backend
            # ejecutó asíncronamente)
            load_job.result()

            logger.info(
                "BigQuery Load Job completado exitosamente",
                extra={
                    "attributes": {
                        "job_id": load_job.job_id,
                        "rows_loaded": getattr(load_job, "output_rows", 0),
                        "state": load_job.state,
                    },
                },
            )

            return load_job.job_id

        except Exception as exc:
            raise BigQueryConnectionError(
                f"Fallo durante ejecución transaccional a BigQuery: {exc}"
            ) from exc

    # ── Métodos Internos ──────────────────────────────────────────────

    def _get_blob_md5_hash(self, gcs_uri: str, storage_module: Any) -> str:
        """Extrae la propiedad md5_hash nativa del Blob de GCS.

        Parameters
        ----------
        gcs_uri : str
            URI completa (ej. ``gs://my-bucket/gold/file.parquet``).
        storage_module : module
            Módulo ``google.cloud.storage`` ya importado.

        Returns
        -------
        str
            Hash MD5 en codificación Base64 proporcionado por GCP.
        """
        prefix = f"gs://{self._bucket_name}/"
        if not gcs_uri.startswith(prefix):
            raise ValueError(f"La URI {gcs_uri} no pertenece al bucket {self._bucket_name}")

        blob_name = gcs_uri[len(prefix) :]

        client = (
            storage_module.Client.from_service_account_json(self._credentials_path)
            if self._credentials_path
            else storage_module.Client()
        )

        bucket = client.bucket(self._bucket_name)
        blob = bucket.get_blob(blob_name)

        if not blob or not blob.md5_hash:
            raise ValueError(f"No se pudo recuperar metadata del blob: {blob_name}")

        return blob.md5_hash

    def _generate_deterministic_job_id(self, gcs_uri: str, blob_md5: str) -> str:
        """Aplica la fórmula matemática estricta del PRD §4.

        ``job_id = "pvod_load_" + hashlib.md5(
            source_uri + project_id + dataset_id + target_table + hash_contenido_parquet
        ).hexdigest()``
        """
        raw_seed = (
            f"{gcs_uri}{self._project_id}{self._dataset_id}"
            f"{self._table_id}{blob_md5}"
        )
        hashed_seed = hashlib.md5(raw_seed.encode("utf-8")).hexdigest()
        return f"pvod_load_{hashed_seed}"

    def _build_load_job_config(self, bq_module: Any) -> Any:
        """Construye y retorna el ``LoadJobConfig`` con clustering y particionamiento.

        Parquet provee su propio esquema en el backend, no requerimos
        definir un SchemaField explícito a menos que BQ lo pida (rara vez).
        """
        job_config = bq_module.LoadJobConfig()
        job_config.source_format = bq_module.SourceFormat.PARQUET

        # PRD §4: Idempotencia y modo de escritura
        # Si el LoadJob tiene el mismo Job ID BQ evita procesarlo de nuevo.
        # En caso de una carga legítima distinta pero que coincida en la tabla,
        # añadimos registros (Append).
        job_config.write_disposition = bq_module.WriteDisposition.WRITE_APPEND

        # PRD §4: Particionamiento y Clustering
        job_config.time_partitioning = bq_module.TimePartitioning(
            type_=bq_module.TimePartitioningType.DAY,
            field=TEMPORAL_COLUMN,
        )
        job_config.clustering_fields = [STATION_COLUMN]

        return job_config
