"""
infrastructure/gcs_parquet_exporter.py — Exportador Parquet a GCS (Capa Oro)
==============================================================================
Implementación concreta de ``GoldLayerExportPort`` que:

1. Aplica enforcement de tipos estrictos según el esquema final PVOD.
2. Serializa el DataFrame a Apache Parquet con compresión Zstandard
   (PyArrow aplica RLE + dictionary encoding automáticamente por columna).
3. Sube el archivo Parquet al bucket GCS configurado (Capa Oro).
4. Retorna el URI ``gs://`` del objeto almacenado.

Referencia PRD §4:
  Exportar de Polars obligatoriamente a formato Apache Parquet
  (con compresión RLE y diccionarios) antes de realizar el Load Job
  masivo a BigQuery.
"""

from __future__ import annotations

import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import polars as pl
from google.cloud import storage

from app.application.gold_layer_port import GoldLayerExportPort
from app.domain.constants import (
    GCS_GOLD_PREFIX,
    PARQUET_BLOB_PREFIX,
    PARQUET_COMPRESSION,
    PVOD_FINAL_SCHEMA,
    STATION_COLUMN,
    TEMPORAL_COLUMN,
)
from app.domain.exceptions import DataTransformationError, SolarETLError

logger = logging.getLogger(__name__)

# ── Mapeo de nombres de tipo a objetos pl.DataType ────────────────────
_TYPE_MAP: dict[str, pl.DataType] = {
    "Float64": pl.Float64,
    "UInt8": pl.UInt8,
    "Datetime": pl.Datetime,
}


class GCSParquetExporter(GoldLayerExportPort):
    """Exporta el DataFrame PVOD limpio a Parquet y lo sube a GCS.

    Parameters
    ----------
    bucket_name : str
        Nombre del bucket GCS (sin prefijo ``gs://``).
    credentials_path : str | None, optional
        Ruta al archivo JSON de credenciales de servicio.
        Si es ``None``, usa Application Default Credentials (ADC).
    """

    def __init__(
        self,
        bucket_name: str,
        *,
        credentials_path: str | None = None,
    ) -> None:
        self._bucket_name = bucket_name
        self._credentials_path = credentials_path

    # ── Contrato ABC ──────────────────────────────────────────────────

    def export_to_gold_layer(self, dataframe: pl.DataFrame) -> str:
        """Exporta el DataFrame a Parquet comprimido y lo sube a GCS.

        Parameters
        ----------
        dataframe : pl.DataFrame
            DataFrame PVOD limpio, post pipeline de limpieza.

        Returns
        -------
        str
            URI GCS del Parquet exportado (``gs://bucket/gold/pvod_*.parquet``).
        """
        logger.info(
            "Iniciando exportación a Capa Oro (GCS Parquet)",
            extra={
                "attributes": {
                    "bucket": self._bucket_name,
                    "rows": dataframe.height,
                    "columns": len(dataframe.columns),
                },
            },
        )

        # ── 1. Enforcement de tipos finales ───────────────────────────
        dataframe = self._enforce_final_schema(dataframe)

        # ── 2. Serialización a Parquet local (tempfile) ───────────────
        parquet_path = self._write_parquet(dataframe)

        # ── 3. Upload a GCS ───────────────────────────────────────────
        blob_name = self._generate_blob_name()
        gcs_uri = self._upload_to_gcs(parquet_path, blob_name)

        logger.info(
            "Exportación a Capa Oro completada",
            extra={
                "attributes": {
                    "gcs_uri": gcs_uri,
                    "parquet_size_mb": round(
                        parquet_path.stat().st_size / (1024 * 1024), 2
                    ),
                    "rows_exported": dataframe.height,
                    "compression": PARQUET_COMPRESSION,
                },
            },
        )

        return gcs_uri

    # ── Métodos Internos ──────────────────────────────────────────────

    @staticmethod
    def _enforce_final_schema(df: pl.DataFrame) -> pl.DataFrame:
        """Aplica enforcement de tipos estrictos según PVOD_FINAL_SCHEMA.

        Verifica que todas las columnas del esquema existan y las castea
        al tipo exacto requerido para la serialización Parquet.

        Parameters
        ----------
        df : pl.DataFrame
            DataFrame a validar y castear.

        Returns
        -------
        pl.DataFrame
            DataFrame con tipos estrictos aplicados.

        Raises
        ------
        DataTransformationError
            Si faltan columnas requeridas en el DataFrame.
        """
        # Verificar columnas requeridas
        missing = set(PVOD_FINAL_SCHEMA.keys()) - set(df.columns)
        if missing:
            raise DataTransformationError(
                f"Faltan columnas requeridas para el export Parquet: {sorted(missing)}"
            )

        # Castear cada columna al tipo final
        cast_exprs = []
        for col_name, type_name in PVOD_FINAL_SCHEMA.items():
            target_type = _TYPE_MAP[type_name]
            cast_exprs.append(pl.col(col_name).cast(target_type))

        df = df.with_columns(cast_exprs)

        # Seleccionar solo las columnas del esquema final (orden definido)
        df = df.select(list(PVOD_FINAL_SCHEMA.keys()))

        logger.info(
            "Enforcement de esquema final aplicado",
            extra={
                "attributes": {
                    "columns": list(PVOD_FINAL_SCHEMA.keys()),
                    "column_count": len(PVOD_FINAL_SCHEMA),
                },
            },
        )

        return df

    @staticmethod
    def _write_parquet(df: pl.DataFrame) -> Path:
        """Serializa el DataFrame a Parquet con compresión Zstandard.

        Usa ``use_pyarrow=True`` para habilitar las optimizaciones de
        encoding de PyArrow (RLE + dictionary encoding automático por columna).

        Parameters
        ----------
        df : pl.DataFrame
            DataFrame con tipos finales ya aplicados.

        Returns
        -------
        Path
            Ruta al archivo Parquet temporal.
        """
        tmp = tempfile.NamedTemporaryFile(
            suffix=".parquet",
            prefix="pvod_gold_",
            delete=False,
        )
        tmp.close()
        parquet_path = Path(tmp.name)

        df.write_parquet(
            file=parquet_path,
            compression=PARQUET_COMPRESSION,
            use_pyarrow=True,
        )

        size_mb = parquet_path.stat().st_size / (1024 * 1024)
        logger.info(
            "DataFrame serializado a Parquet",
            extra={
                "attributes": {
                    "path": str(parquet_path),
                    "size_mb": round(size_mb, 2),
                    "compression": PARQUET_COMPRESSION,
                    "rows": df.height,
                },
            },
        )

        return parquet_path

    @staticmethod
    def _generate_blob_name() -> str:
        """Genera el nombre del blob en GCS con timestamp UTC.

        Returns
        -------
        str
            Nombre del blob: ``gold/pvod_YYYYMMDD_HHMMSS.parquet``
        """
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        return f"{GCS_GOLD_PREFIX}{PARQUET_BLOB_PREFIX}{ts}.parquet"

    def _upload_to_gcs(self, local_path: Path, blob_name: str) -> str:
        """Sube el archivo Parquet al bucket GCS configurado.

        Parameters
        ----------
        local_path : Path
            Ruta al archivo Parquet local.
        blob_name : str
            Nombre del blob destino en GCS.

        Returns
        -------
        str
            URI GCS completa: ``gs://bucket/blob_name``

        Raises
        ------
        SolarETLError
            Si falla la conexión o el upload a GCS.
        """
        try:
            client = storage.Client.from_service_account_json(
                self._credentials_path
            ) if self._credentials_path else storage.Client()

            bucket = client.bucket(self._bucket_name)
            blob = bucket.blob(blob_name)

            blob.upload_from_filename(
                str(local_path),
                content_type="application/octet-stream",
            )

            gcs_uri = f"gs://{self._bucket_name}/{blob_name}"

            logger.info(
                "Parquet subido a GCS exitosamente",
                extra={
                    "attributes": {
                        "gcs_uri": gcs_uri,
                        "bucket": self._bucket_name,
                        "blob": blob_name,
                    },
                },
            )

            return gcs_uri

        except Exception as exc:
            raise SolarETLError(
                f"Error al subir Parquet a GCS "
                f"(bucket={self._bucket_name}, blob={blob_name}): {exc}"
            ) from exc
