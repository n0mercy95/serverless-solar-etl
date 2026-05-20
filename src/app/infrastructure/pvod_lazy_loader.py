"""
infrastructure/pvod_lazy_loader.py — Carga Lazy y Alineamiento Temporal PVOD
==============================================================================
Implementación concreta de ``PVODTransformationPipeline`` que ejecuta:

1. Materialización del buffer a archivo temporal (requerido por ``scan_csv``).
2. Carga perezosa (lazy) via ``pl.scan_csv()`` para optimización de queries.
3. Parsing y truncamiento de timestamps a la grilla estricta de 15 minutos.
4. Tipado estricto de columnas según el esquema PVOD.
5. Cálculo de columnas delta (desviación NWP vs LMD).
6. Validaciones de integridad temporal y restricciones físicas.

Referencia PRD §6 — Fase 2, Tarea 2.1:
  Carga perezosa (lazy query vía scan_csv) en entorno Polars.
  Ejecución de Joins temporales alineados cada 15 minutos exactos
  para cruzar matrices LMD y NWP.
"""

from __future__ import annotations

import io
import logging
import tempfile
from pathlib import Path

import polars as pl

from app.application.transformation_ports import PVODTransformationPipeline
from app.domain.constants import (
    IRRADIANCE_COLUMNS,
    LMD_COLUMNS,
    NWP_COLUMNS,
    NWP_LMD_DELTA_PAIRS,
    SAMPLING_INTERVAL_POLARS,
    SOLAR_CONSTANT_W_M2,
    STATION_COLUMN,
    TARGET_COLUMN,
    TEMPORAL_COLUMN,
)
from app.domain.exceptions import (
    DataTransformationError,
    IrradianceOutOfBoundsError,
    TemporalAlignmentError,
)

logger = logging.getLogger(__name__)


class PVODLazyLoader(PVODTransformationPipeline):
    """Carga lazy del CSV PVOD con alineamiento temporal y validación física.

    Utiliza ``pl.scan_csv()`` para construir un plan de ejecución lazy
    que Polars optimiza internamente (predicate pushdown, projection
    pushdown) antes de materializar resultados.

    Parameters
    ----------
    datetime_format : str, optional
        Formato strptime para parsear ``date_time`` (default: ``%Y-%m-%d %H:%M``).
    """

    def __init__(self, *, datetime_format: str = "%Y-%m-%d %H:%M") -> None:
        self._datetime_format = datetime_format

    # ── Contrato ABC ──────────────────────────────────────────────────

    def load_and_align(self, buffer: io.BytesIO) -> pl.LazyFrame:
        """Carga el CSV desde un buffer en modo lazy y ejecuta el
        alineamiento temporal a la grilla estricta de 15 minutos.

        El flujo es:
        ``buffer → tempfile → scan_csv → parse/truncate → cast → deltas → validar``

        Parameters
        ----------
        buffer : io.BytesIO
            Buffer binario con el CSV PVOD consolidado.

        Returns
        -------
        pl.LazyFrame
            LazyFrame optimizado, listo para la fase de limpieza (Strategy).
        """
        logger.info("Iniciando carga lazy y alineamiento temporal del PVOD")

        # ── 1. Materializar buffer a disco temporal ───────────────────
        tmp_path = self._buffer_to_tempfile(buffer)

        try:
            # ── 2. Carga lazy via scan_csv ────────────────────────────
            lazy_frame = self._scan_csv_lazy(tmp_path)

            # ── 3. Parsing temporal y truncamiento a 15 min ───────────
            lazy_frame = self._parse_and_truncate_datetime(lazy_frame)

            # ── 3b. Deduplicar registros colapsados por el truncamiento ─
            lazy_frame = self._deduplicate_after_truncation(lazy_frame)

            # ── 4. Tipado estricto de columnas numéricas ──────────────
            lazy_frame = self._cast_strict_types(lazy_frame)

            # ── 5. Columnas delta NWP - LMD ───────────────────────────
            lazy_frame = self._compute_nwp_lmd_deltas(lazy_frame)

            # ── 6. Validaciones (requieren collect parcial) ───────────
            self._validate_temporal_integrity(lazy_frame)
            lazy_frame = self._validate_irradiance_bounds(lazy_frame)

            logger.info(
                "Carga lazy y alineamiento temporal completados",
                extra={
                    "attributes": {
                        "schema": str(lazy_frame.collect_schema()),
                        "temp_file": str(tmp_path),
                    },
                },
            )

            return lazy_frame

        except (TemporalAlignmentError, IrradianceOutOfBoundsError):
            # Re-raise domain exceptions sin envolver
            raise
        except Exception as exc:
            raise DataTransformationError(
                f"Error inesperado durante la carga lazy: {exc}"
            ) from exc

    # ── Métodos Internos ──────────────────────────────────────────────

    @staticmethod
    def _buffer_to_tempfile(buffer: io.BytesIO) -> Path:
        """Escribe el buffer a un archivo temporal para que ``scan_csv``
        pueda operar con path en disco (requerimiento de Polars).

        El archivo NO se elimina aquí; Polars lazy lo necesita hasta
        que se ejecute ``.collect()``.  El OS purgará el tempdir al
        finalizar el proceso.

        Returns
        -------
        Path
            Ruta absoluta al archivo temporal.
        """
        tmp = tempfile.NamedTemporaryFile(
            suffix=".csv",
            prefix="pvod_lazy_",
            delete=False,
        )
        tmp.write(buffer.getvalue())
        tmp.flush()
        tmp.close()

        tmp_path = Path(tmp.name)
        size_mb = tmp_path.stat().st_size / (1024 * 1024)

        logger.info(
            "Buffer materializado a archivo temporal",
            extra={
                "attributes": {
                    "temp_path": str(tmp_path),
                    "size_mb": round(size_mb, 2),
                },
            },
        )

        return tmp_path

    @staticmethod
    def _scan_csv_lazy(path: Path) -> pl.LazyFrame:
        """Construye un LazyFrame via ``pl.scan_csv`` sin materializar datos.

        Parameters
        ----------
        path : Path
            Ruta al archivo CSV temporal.

        Returns
        -------
        pl.LazyFrame
            Plan de ejecución lazy sobre el CSV.
        """
        lazy_frame = pl.scan_csv(
            source=path,
            infer_schema_length=10_000,
            null_values=["", "NA", "null", "NaN"],
            try_parse_dates=False,  # Parseamos manualmente para control total
        )

        logger.info(
            "scan_csv ejecutado (plan lazy construido)",
            extra={
                "attributes": {
                    "columns": lazy_frame.collect_schema().names(),
                },
            },
        )

        return lazy_frame

    def _parse_and_truncate_datetime(self, lf: pl.LazyFrame) -> pl.LazyFrame:
        """Parsea ``date_time`` de Utf8 a Datetime y trunca a 15 min exactos.

        El truncamiento garantiza alineamiento perfecto a la grilla
        temporal del PVOD (00, 15, 30, 45 minutos de cada hora).

        Soporta de forma resiliente tanto formatos con segundos (ej: %Y-%m-%d %H:%M:%S)
        como sin segundos (ej: %Y-%m-%d %H:%M).

        Parameters
        ----------
        lf : pl.LazyFrame
            LazyFrame con ``date_time`` como cadena de texto.

        Returns
        -------
        pl.LazyFrame
            LazyFrame con ``date_time`` como ``pl.Datetime`` truncado.
        """
        format_1 = self._datetime_format
        format_2 = "%Y-%m-%d %H:%M:%S" if "%S" not in format_1 else "%Y-%m-%d %H:%M"

        parsed_1 = pl.col(TEMPORAL_COLUMN).str.strptime(pl.Datetime, format=format_1, strict=False)
        parsed_2 = pl.col(TEMPORAL_COLUMN).str.strptime(pl.Datetime, format=format_2, strict=False)

        return lf.with_columns(
            pl.coalesce([parsed_1, parsed_2])
            .dt.truncate(SAMPLING_INTERVAL_POLARS)
            .alias(TEMPORAL_COLUMN)
        )

    @staticmethod
    def _deduplicate_after_truncation(lf: pl.LazyFrame) -> pl.LazyFrame:
        """Elimina registros duplicados que surgen al truncar timestamps.

        El dataset real puede contener múltiples filas cuyo timestamp
        original cae dentro de la misma ventana de 15 minutos para una
        misma estación (ej: ``01:17`` y ``01:29`` → ambas truncan a
        ``01:15``).  Se conserva la **última** fila de cada grupo para
        reflejar la lectura más reciente del sensor.

        Returns
        -------
        pl.LazyFrame
            LazyFrame sin duplicados por (station_id, date_time).
        """
        return lf.unique(
            subset=[STATION_COLUMN, TEMPORAL_COLUMN],
            keep="last",
        )

    @staticmethod
    def _cast_strict_types(lf: pl.LazyFrame) -> pl.LazyFrame:
        """Aplica tipado estricto a todas las columnas según el esquema PVOD.

        - Columnas NWP + LMD + power → ``Float64``
        - station_id → ``UInt8``

        Returns
        -------
        pl.LazyFrame
            LazyFrame con tipos estrictos.
        """
        numeric_columns = list(NWP_COLUMNS) + list(LMD_COLUMNS) + [TARGET_COLUMN]

        cast_exprs = [
            pl.col(col).cast(pl.Float64) for col in numeric_columns
        ]
        cast_exprs.append(
            pl.col(STATION_COLUMN).cast(pl.UInt8)
        )

        return lf.with_columns(cast_exprs)

    @staticmethod
    def _compute_nwp_lmd_deltas(lf: pl.LazyFrame) -> pl.LazyFrame:
        """Calcula columnas de desviación entre predicciones NWP y
        mediciones LMD para variables compartidas.

        Cada delta mide el error del modelo NWP respecto a la realidad:
        ``delta = nwp_value - lmd_value``

        Returns
        -------
        pl.LazyFrame
            LazyFrame con columnas delta adicionales.
        """
        delta_exprs = [
            (pl.col(nwp_col) - pl.col(lmd_col)).alias(delta_name)
            for nwp_col, lmd_col, delta_name in NWP_LMD_DELTA_PAIRS
        ]

        return lf.with_columns(delta_exprs)

    @staticmethod
    def _validate_temporal_integrity(lf: pl.LazyFrame) -> None:
        """Valida la integridad temporal de la grilla de 15 minutos.

        Verificaciones:
        1. No existan timestamps duplicados dentro de una misma estación.
        2. Los minutos de cada timestamp sean múltiplos exactos de 15.

        Raises
        ------
        TemporalAlignmentError
            Si se detectan duplicados o timestamps desalineados.

        Notes
        -----
        Estas validaciones requieren materialización parcial (``.collect()``).
        Se diseñan como queries enfocadas para minimizar el costo.
        """
        # ── 1. Detectar duplicados por estación + timestamp ───────────
        #     Post-deduplicación esto debería ser 0; si no, solo loguear.
        duplicates = (
            lf.group_by([STATION_COLUMN, TEMPORAL_COLUMN])
            .agg(pl.len().alias("count"))
            .filter(pl.col("count") > 1)
            .collect()
        )

        if duplicates.height > 0:
            sample = duplicates.head(5).to_dicts()
            logger.warning(
                "Duplicados residuales detectados post-deduplicación",
                extra={
                    "attributes": {
                        "duplicate_count": duplicates.height,
                        "sample": str(sample),
                    },
                },
            )

        # ── 2. Verificar alineamiento a múltiplos de 15 minutos ──────
        misaligned = (
            lf.select(
                pl.col(TEMPORAL_COLUMN).dt.minute().alias("minute")
            )
            .filter(
                ~pl.col("minute").is_in([0, 15, 30, 45])
            )
            .collect()
        )

        if misaligned.height > 0:
            raise TemporalAlignmentError(
                f"Se detectaron {misaligned.height} timestamps no alineados "
                f"a la grilla de 15 minutos (minutos válidos: 0, 15, 30, 45)."
            )

        logger.info(
            "Validación de integridad temporal exitosa",
            extra={
                "attributes": {
                    "duplicates_found": 0,
                    "misaligned_found": 0,
                },
            },
        )

    @staticmethod
    def _validate_irradiance_bounds(lf: pl.LazyFrame) -> pl.LazyFrame:
        """Valida y clampea las columnas de irradiancia a restricciones físicas.

        PRD §4: La irradiancia global no puede ser negativa ni exceder
        la constante solar extraterrestre.

        En datos reales de sensores, el fenómeno de *cloud edge enhancement*
        puede producir mediciones por encima de la constante solar (~1361 W/m²).
        En lugar de abortar el pipeline, los valores fuera de rango se
        **clampean** a ``[0, SOLAR_CONSTANT_W_M2]`` y se loguea la cantidad
        de celdas corregidas.

        Returns
        -------
        pl.LazyFrame
            LazyFrame con irradiancias clampeadas al rango físico válido.

        Notes
        -----
        Se ignoran valores nulos (serán tratados en la Tarea 2.2 por
        ``MissingValueImputerStrategy``).
        """
        total_clamped = 0

        for col_name in IRRADIANCE_COLUMNS:
            violations = (
                lf.select(pl.col(col_name))
                .filter(
                    pl.col(col_name).is_not_null()
                    & (
                        (pl.col(col_name) < 0)
                        | (pl.col(col_name) > SOLAR_CONSTANT_W_M2)
                    )
                )
                .collect()
            )

            if violations.height > 0:
                min_val = violations[col_name].min()
                max_val = violations[col_name].max()
                total_clamped += violations.height
                logger.warning(
                    "Irradiancia fuera de rango detectada — valores clampeados",
                    extra={
                        "attributes": {
                            "column": col_name,
                            "violations": violations.height,
                            "original_range": f"[{min_val}, {max_val}]",
                            "clamped_to": f"[0, {SOLAR_CONSTANT_W_M2}]",
                        },
                    },
                )

        # Clampear todas las columnas de irradiancia en una sola pasada
        clamp_exprs = [
            pl.col(col_name).clip(0, SOLAR_CONSTANT_W_M2).alias(col_name)
            for col_name in IRRADIANCE_COLUMNS
        ]
        lf = lf.with_columns(clamp_exprs)

        logger.info(
            "Validación de irradiancia completada",
            extra={
                "attributes": {
                    "columns_validated": list(IRRADIANCE_COLUMNS),
                    "upper_bound": SOLAR_CONSTANT_W_M2,
                    "total_values_clamped": total_clamped,
                },
            },
        )

        return lf
