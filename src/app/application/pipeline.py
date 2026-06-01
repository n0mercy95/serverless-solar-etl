"""
application/pipeline.py — Orquestador del Pipeline ETL Solar Completo
=======================================================================
Caso de uso principal que conecta las 5 fases del ETL en secuencia:

  1. **Extracción** (Fase 1.2) — Factory Pattern con fallback automático.
  2. **Carga Lazy + Joins Temporales** (Fase 2.1) — ``scan_csv`` + alineamiento 15 min.
  3. **Limpieza Heurística** (Fase 2.2) — Strategy Pattern (Hampel, Zeroing, Imputer).
  4. **Export Parquet → GCS** (Fase 2.3) — Capa Oro con compresión Zstandard.
  5. **Load Job → BigQuery** (Fase 3.2) — Carga idempotente con MD5 determinista.

Este módulo reside en la capa de **Application** porque coordina casos de
uso sin conocer detalles de infraestructura.  Todas las dependencias se
inyectan vía constructor (Dependency Injection) para facilitar testing y
respetar la Regla de Dependencia de Clean Architecture.

Referencia PRD §2:
  Orquestación: Cloud Scheduler o Cloud Tasks para la invocación asíncrona
  y orquestación de la carga del pipeline ETL.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.application.cleaning_pipeline import CleaningPipelineExecutor
from app.application.config import Settings
from app.application.data_profiler import DataProfiler
from app.application.scatter_plot_generator import ScatterPlotGenerator
from app.application.data_warehouse_port import DataWarehouseRepository
from app.application.extraction_factory import ExtractionFactory
from app.application.gold_layer_port import GoldLayerExportPort
from app.application.transformation_ports import PVODTransformationPipeline
from app.domain.exceptions import SolarETLError

logger = logging.getLogger(__name__)


# ── Resultado del Pipeline ────────────────────────────────────────────


@dataclass(frozen=True)
class PipelineResult:
    """Resultado inmutable de una ejecución completa del pipeline ETL.

    Attributes
    ----------
    records_processed : int
        Cantidad de registros procesados y cargados.
    gcs_uri : str
        URI del Parquet exportado a la Capa Oro (``gs://...``).
    bigquery_job_id : str
        Identificador determinista del Load Job de BigQuery.
    duration_seconds : float
        Duración total de la ejecución en segundos.
    started_at : str
        Timestamp ISO 8601 UTC del inicio de la ejecución.
    completed_at : str
        Timestamp ISO 8601 UTC del fin de la ejecución.
    steps_completed : list[str]
        Lista de pasos completados exitosamente.
    """

    records_processed: int
    gcs_uri: str
    bigquery_job_id: str
    duration_seconds: float
    started_at: str
    completed_at: str
    steps_completed: list[str] = field(default_factory=list)


# ── Pipeline Orquestador ──────────────────────────────────────────────


class SolarETLPipeline:
    """Caso de uso: ejecuta el pipeline ETL completo del dataset PVOD.

    Conecta las 5 fases del PRD en secuencia, delegando cada paso a su
    módulo especializado.  Este orquestador NO conoce detalles de
    infraestructura — solo invoca contratos abstractos (puertos).

    Parameters
    ----------
    settings : Settings
        Configuración centralizada del proyecto.
    extraction_factory : ExtractionFactory
        Factory con fallback para la descarga del CSV.
    transformation_pipeline : PVODTransformationPipeline
        Servicio de carga lazy y alineamiento temporal.
    cleaning_executor : CleaningPipelineExecutor
        Orquestador de estrategias de limpieza (Hampel, Zeroing, Imputer).
    gold_exporter : GoldLayerExportPort
        Exportador de Parquet comprimido a GCS.
    warehouse : DataWarehouseRepository
        Adaptador para carga idempotente a BigQuery.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        extraction_factory: ExtractionFactory,
        transformation_pipeline: PVODTransformationPipeline,
        cleaning_executor: CleaningPipelineExecutor,
        gold_exporter: GoldLayerExportPort,
        warehouse: DataWarehouseRepository,
        scatter_plot_generator: ScatterPlotGenerator,
    ) -> None:
        self._settings = settings
        self._extraction_factory = extraction_factory
        self._transformation_pipeline = transformation_pipeline
        self._cleaning_executor = cleaning_executor
        self._gold_exporter = gold_exporter
        self._warehouse = warehouse
        self._scatter_plot_generator = scatter_plot_generator

    def execute(self) -> PipelineResult:
        """Ejecuta el pipeline ETL completo de principio a fin.

        Returns
        -------
        PipelineResult
            Resultado inmutable con métricas de la ejecución.

        Raises
        ------
        SolarETLError
            Si cualquier fase del pipeline falla.  La excepción específica
            (``DataExtractionError``, ``DataTransformationError``,
            ``BigQueryConnectionError``, etc.) se propaga sin envolver.
        """
        started_at = datetime.now(timezone.utc)
        t0 = time.monotonic()
        steps_completed: list[str] = []

        logger.info(
            "═══ Pipeline ETL Solar PVOD — Inicio ═══",
            extra={
                "attributes": {
                    "environment": self._settings.environment,
                    "started_at": started_at.isoformat(),
                },
            },
        )

        try:
            # ── Paso 1: Extracción (Fase 1.2 — Factory Pattern) ──────
            logger.info("▶ Paso 1/5: Extracción del CSV PVOD")
            buffer = self._extraction_factory.extract_with_fallback()
            csv_md5 = hashlib.md5(buffer.getvalue()).hexdigest()
            buffer_size_mb = round(buffer.getbuffer().nbytes / (1024 * 1024), 2)
            steps_completed.append("extraction")

            logger.info(
                "✓ Paso 1/5 completado: CSV descargado",
                extra={
                    "attributes": {"buffer_size_mb": buffer_size_mb},
                },
            )

            # ── Paso 2: Carga Lazy + Joins Temporales (Fase 2.1) ─────
            logger.info("▶ Paso 2/5: Carga lazy y alineamiento temporal")
            lazy_frame = self._transformation_pipeline.load_and_align(buffer)
            dataframe = lazy_frame.collect()
            rows_loaded = dataframe.height
            steps_completed.append("transformation")

            logger.info(
                "✓ Paso 2/5 completado: LazyFrame materializado",
                extra={
                    "attributes": {
                        "rows": rows_loaded,
                        "columns": len(dataframe.columns),
                    },
                },
            )

            # ── Data Profiling: Pre-Cleaning ──────────────────────────
            logger.info("Ejecutando Data Profiling: Pre-Cleaning")
            pre_profiler = DataProfiler(dataframe)
            pre_report = pre_profiler.generate_report("Pre-Cleaning")
            logger.info(f"\n{pre_report}")

            # ── Paso 3: Limpieza Heurística (Fase 2.2 — Strategy) ───
            logger.info("▶ Paso 3/5: Pipeline de limpieza heurística")
            clean_df = self._cleaning_executor.execute(dataframe)
            rows_after_cleaning = clean_df.height
            steps_completed.append("cleaning")

            logger.info(
                "✓ Paso 3/5 completado: Datos limpios",
                extra={
                    "attributes": {
                        "rows_before": rows_loaded,
                        "rows_after": rows_after_cleaning,
                    },
                },
            )

            # ── Data Profiling: Post-Cleaning (Gold) ──────────────────
            logger.info("Ejecutando Data Profiling: Post-Cleaning (Gold)")
            post_profiler = DataProfiler(clean_df)
            post_report = post_profiler.generate_report("Post-Cleaning (Gold)")
            logger.info(f"\n{post_report}")

            # ── Scatter Plots: NWP vs LMD Irradiance ─────────────────
            logger.info("Generando scatter plots NWP vs LMD (Pre/Post Cleaning)")
            plot_uris = self._scatter_plot_generator.generate_and_upload(
                df_pre=dataframe,
                df_post=clean_df,
                content_hash=csv_md5,
            )
            if plot_uris:
                logger.info(
                    f"Scatter plots generados y subidos: {len(plot_uris)} archivos",
                    extra={
                        "attributes": {"plot_uris": plot_uris},
                    },
                )

            # ── Paso 4: Export Parquet → GCS (Fase 2.3 — Gold Layer) ─
            logger.info("▶ Paso 4/5: Exportación Parquet a Capa Oro (GCS)")
            gcs_uri = self._gold_exporter.export_to_gold_layer(
                clean_df, content_hash=csv_md5
            )
            steps_completed.append("gold_export")

            logger.info(
                "✓ Paso 4/5 completado: Parquet en GCS",
                extra={
                    "attributes": {"gcs_uri": gcs_uri},
                },
            )

            # ── Paso 5: Load Job → BigQuery (Fase 3.2 — Adapter) ────
            logger.info("▶ Paso 5/5: Carga idempotente a BigQuery")
            job_id = self._warehouse.load_dataframe_idempotent(gcs_uri)
            steps_completed.append("bigquery_load")

            logger.info(
                "✓ Paso 5/5 completado: Datos en BigQuery",
                extra={
                    "attributes": {"job_id": job_id},
                },
            )

            # ── Resultado Final ──────────────────────────────────────
            completed_at = datetime.now(timezone.utc)
            duration = round(time.monotonic() - t0, 2)

            result = PipelineResult(
                records_processed=rows_after_cleaning,
                gcs_uri=gcs_uri,
                bigquery_job_id=job_id,
                duration_seconds=duration,
                started_at=started_at.isoformat(),
                completed_at=completed_at.isoformat(),
                steps_completed=steps_completed,
            )

            logger.info(
                "═══ Pipeline ETL Solar PVOD — Completado ═══",
                extra={
                    "attributes": {
                        "records_processed": result.records_processed,
                        "gcs_uri": result.gcs_uri,
                        "bigquery_job_id": result.bigquery_job_id,
                        "duration_seconds": result.duration_seconds,
                        "steps_completed": result.steps_completed,
                    },
                },
            )

            return result

        except SolarETLError:
            # Re-raise excepciones del dominio sin envolver
            duration = round(time.monotonic() - t0, 2)
            logger.error(
                "═══ Pipeline ETL Solar PVOD — Fallido ═══",
                extra={
                    "attributes": {
                        "duration_seconds": duration,
                        "steps_completed": steps_completed,
                        "failed_at_step": len(steps_completed) + 1,
                    },
                },
            )
            raise

        except Exception as exc:
            duration = round(time.monotonic() - t0, 2)
            logger.error(
                "═══ Pipeline ETL Solar PVOD — Error Inesperado ═══",
                extra={
                    "attributes": {
                        "duration_seconds": duration,
                        "steps_completed": steps_completed,
                        "error": str(exc),
                    },
                },
            )
            raise SolarETLError(
                f"Error inesperado durante el pipeline ETL: {exc}"
            ) from exc


# ── Factory Function ──────────────────────────────────────────────────


def build_pipeline(settings: Settings) -> SolarETLPipeline:
    """Construye el pipeline ETL con todas sus dependencias inyectadas.

    Esta función es el **Composition Root** que resuelve todas las
    dependencias concretas y las inyecta al orquestador.  Es la única
    parte del sistema que conoce las implementaciones de infraestructura.

    Parameters
    ----------
    settings : Settings
        Configuración centralizada validada.

    Returns
    -------
    SolarETLPipeline
        Instancia lista para ejecutar ``.execute()``.
    """
    from app.application.cleaning_strategy_port import SolarDataCleaningStrategy
    from app.infrastructure.bigquery_adapter import BigQueryAdapter
    from app.infrastructure.gcs_parquet_exporter import GCSParquetExporter
    from app.infrastructure.pvod_lazy_loader import PVODLazyLoader
    from app.infrastructure.strategies.hampel_filter_strategy import (
        HampelFilterStrategy,
    )
    from app.infrastructure.strategies.irradiance_outlier_strategy import (
        IrradianceOutlierStrategy,
    )
    from app.infrastructure.strategies.missing_value_imputer_strategy import (
        MissingValueImputerStrategy,
    )
    from app.infrastructure.strategies.nighttime_zeroing_strategy import (
        NighttimeZeroingStrategy,
    )
    from app.infrastructure.strategies.thermodynamic_bounds_strategy import (
        ThermodynamicBoundsStrategy,
    )

    # ── Fase 1.2: Extracción ─────────────────────────────────────────
    extraction_factory = ExtractionFactory(settings)

    # ── Fase 2.1: Transformación ─────────────────────────────────────
    transformation_pipeline = PVODLazyLoader()

    # ── Fase 2.2: Limpieza (orden importa — PRD §3) ─────────────────
    strategies: list[SolarDataCleaningStrategy] = [
        NighttimeZeroingStrategy(),     # 1. Forma física del ciclo diurno
        ThermodynamicBoundsStrategy(),  # 2. Límites físicos y termodinámicos absolutos [NEW]
        IrradianceOutlierStrategy(),    # 3. Filtrar desviaciones NWP vs LMD
        HampelFilterStrategy(),         # 4. Filtrar anomalías de viento
        MissingValueImputerStrategy(),  # 5. Interpolar gaps restantes (incl. nulls del paso 2)
    ]
    cleaning_executor = CleaningPipelineExecutor(strategies=strategies)

    # ── Fase 2.3: Export Gold Layer ──────────────────────────────────
    gold_exporter = GCSParquetExporter(
        bucket_name=settings.gcs_bucket_name,
    )

    # ── Fase 3.2: BigQuery Load ──────────────────────────────────────
    warehouse = BigQueryAdapter(
        project_id=settings.gcp_project_id,
        dataset_id=settings.bq_dataset_id,
        table_id=settings.bq_table_id,
        bucket_name=settings.gcs_bucket_name,
    )

    # ── Scatter Plot Generator ────────────────────────────────────
    scatter_plot_generator = ScatterPlotGenerator(
        bucket_name=settings.gcs_bucket_name,
    )

    return SolarETLPipeline(
        settings=settings,
        extraction_factory=extraction_factory,
        transformation_pipeline=transformation_pipeline,
        cleaning_executor=cleaning_executor,
        gold_exporter=gold_exporter,
        warehouse=warehouse,
        scatter_plot_generator=scatter_plot_generator,
    )
