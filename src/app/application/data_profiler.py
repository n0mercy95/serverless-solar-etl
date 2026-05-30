"""
application/data_profiler.py — Componente de Data Profiling y Observabilidad
========================================================================
Este componente calcula de forma vectorizada métricas de calidad y
generación de reportes ASCII para los datasets solares en el pipeline.
"""

from __future__ import annotations

import logging
import math
import time
from datetime import datetime
from typing import Union

import polars as pl

from app.domain.constants import DEFAULT_STATION_LATITUDE, TEMPORAL_COLUMN

logger = logging.getLogger(__name__)


class DataProfiler:
    """Componente de profiling en memoria para observabilidad de calidad de datos.

    Calcula métricas clave en una única pasada vectorizada con Polars.
    """

    def __init__(self, df_or_lf: Union[pl.DataFrame, pl.LazyFrame]) -> None:
        """Inicializa el profiler recibiendo un DataFrame o LazyFrame de Polars.

        Parameters
        ----------
        df_or_lf : Union[pl.DataFrame, pl.LazyFrame]
            Datos a perfilar. Si es LazyFrame, se materializará mediante .collect().
        """
        if isinstance(df_or_lf, pl.LazyFrame):
            self._df = df_or_lf.collect()
        else:
            self._df = df_or_lf

        # Mapeo estricto de columnas físicas del esquema
        self._col_mapping = {
            "NWP_GHI": "nwp_globalirrad",
            "LMD_GHI": "lmd_totalirrad",
            "Power": "power",
            "Wind Speed": "lmd_windspeed",
        }

    def generate_report(self, phase_name: str) -> str:
        """Calcula las métricas de calidad y devuelve el reporte en formato ASCII.

        Parameters
        ----------
        phase_name : str
            Nombre de la fase (ej: "Pre-Cleaning", "Post-Cleaning (Gold)")

        Returns
        -------
        str
            Reporte completo en formato ASCII.
        """
        t0 = time.perf_counter()

        total_records = self._df.height
        if total_records == 0:
            # Manejo resiliente de dataframe vacío
            execution_time = round(time.perf_counter() - t0, 4)
            return self._build_ascii_report(
                phase_name=phase_name,
                total_records=0,
                min_date="N/A",
                max_date="N/A",
                execution_time=execution_time,
                metrics={col: self._empty_metrics() for col in self._col_mapping},
                overall_score=100.0,
            )

        # ── 1. Obtener rango de timestamps ────────────────────────────────────
        min_date_raw = self._df[TEMPORAL_COLUMN].min()
        max_date_raw = self._df[TEMPORAL_COLUMN].max()

        min_date = (
            min_date_raw.strftime("%Y-%m-%d %H:%M:%S")
            if isinstance(min_date_raw, datetime) and min_date_raw is not None
            else str(min_date_raw)
        )
        max_date = (
            max_date_raw.strftime("%Y-%m-%d %H:%M:%S")
            if isinstance(max_date_raw, datetime) and max_date_raw is not None
            else str(max_date_raw)
        )

        # ── 2. Calcular elevación solar para chequear Nighttime Power ─────────
        # Se calcula utilizando la posición astronómica vectorizada
        lat_rad = math.radians(DEFAULT_STATION_LATITUDE)
        decl_amplitude = 23.45

        df_calc = self._df.with_columns(
            pl.col(TEMPORAL_COLUMN).dt.ordinal_day().alias("_day_of_year"),
            (
                pl.col(TEMPORAL_COLUMN).dt.hour()
                + pl.col(TEMPORAL_COLUMN).dt.minute() / 60.0
            ).alias("_hour_decimal"),
        )

        df_calc = df_calc.with_columns(
            (
                math.radians(decl_amplitude)
                * (
                    (2.0 * math.pi / 365.0 * (284.0 + pl.col("_day_of_year")))
                    .sin()
                )
            ).alias("_declination_rad"),
            (
                math.radians(15.0) * (pl.col("_hour_decimal") - 12.0)
            ).alias("_hour_angle_rad"),
        )

        df_calc = df_calc.with_columns(
            (
                math.sin(lat_rad) * pl.col("_declination_rad").sin()
                + math.cos(lat_rad)
                * pl.col("_declination_rad").cos()
                * pl.col("_hour_angle_rad").cos()
            )
            .arcsin()
            .alias("_solar_elevation_rad"),
        )

        # ── 3. Construir única query select vectorizada de Polars ─────────────
        select_exprs = []
        for label, col_name in self._col_mapping.items():
            select_exprs.extend(
                [
                    pl.col(col_name).is_null().sum().alias(f"{label}_nulls"),
                    (pl.col(col_name) < 0.0).sum().alias(f"{label}_negatives"),
                    pl.col(col_name).mean().alias(f"{label}_mean"),
                    pl.col(col_name).std().alias(f"{label}_std"),
                    pl.col(col_name).min().alias(f"{label}_min"),
                    pl.col(col_name).max().alias(f"{label}_max"),
                ]
            )

        # Nighttime Power > 0
        # GHI (Local Measurement) = lmd_totalirrad
        # Elevación solar <= 0
        is_nighttime = (pl.col("_solar_elevation_rad") <= 0.0) | (
            pl.col("lmd_totalirrad") == 0.0
        )
        select_exprs.append(
            ((pl.col("power") > 0.0) & is_nighttime)
            .sum()
            .alias("power_nighttime_gt_0")
        )

        # Ejecutar la agregación en un solo select de Polars
        aggregated = df_calc.select(select_exprs)

        # Extraer resultados
        results = aggregated.to_dicts()[0]

        # ── 4. Construir Diccionario de Métricas ──────────────────────────────
        metrics_by_column = {}
        total_issues = 0

        for label, col_name in self._col_mapping.items():
            nulls = results[f"{label}_nulls"]
            negatives = results[f"{label}_negatives"]
            mean_val = results[f"{label}_mean"]
            std_val = results[f"{label}_std"]
            min_val = results[f"{label}_min"]
            max_val = results[f"{label}_max"]

            # Sumar incidencias para el Score
            total_issues += nulls + negatives

            nighttime_val = "N/A"
            if label == "Power":
                nighttime_count = results["power_nighttime_gt_0"]
                nighttime_val = str(nighttime_count)
                total_issues += nighttime_count

            metrics_by_column[label] = {
                "nulls": str(nulls),
                "negatives": str(negatives),
                "nighttime": nighttime_val,
                "mean": f"{mean_val:.1f}" if mean_val is not None else "N/A",
                "std": f"{std_val:.1f}" if std_val is not None else "N/A",
                "min": f"{min_val:.1f}" if min_val is not None else "N/A",
                "max": f"{max_val:.1f}" if max_val is not None else "N/A",
            }

        # Calcular Overall Quality Score
        total_possible = total_records * 4
        score = (
            (1.0 - (total_issues / total_possible)) * 100.0
            if total_possible > 0
            else 100.0
        )
        score = max(0.0, min(100.0, score))  # Clampear por seguridad

        execution_time = round(time.perf_counter() - t0, 4)

        return self._build_ascii_report(
            phase_name=phase_name,
            total_records=total_records,
            min_date=min_date,
            max_date=max_date,
            execution_time=execution_time,
            metrics=metrics_by_column,
            overall_score=score,
        )

    @staticmethod
    def _empty_metrics() -> dict[str, str]:
        """Devuelve diccionario de métricas vacías."""
        return {
            "nulls": "0",
            "negatives": "0",
            "nighttime": "N/A",
            "mean": "N/A",
            "std": "N/A",
            "min": "N/A",
            "max": "N/A",
        }

    @staticmethod
    def _build_ascii_report(
        phase_name: str,
        total_records: int,
        min_date: str,
        max_date: str,
        execution_time: float,
        metrics: dict[str, dict[str, str]],
        overall_score: float,
    ) -> str:
        """Formatea las métricas calculadas exactamente según el diseño ASCII."""
        # Alineación manual y exacta de columnas:
        # Columna 1 (Metric): ancho 24, alineada izquierda
        # Columna 2 (NWP_GHI): ancho 9, alineada izquierda
        # Columna 3 (LMD_GHI): ancho 9, alineada izquierda
        # Columna 4 (Power (MW)): ancho 11, alineada izquierda (el encabezado es Power (MW), así que ancho 11)
        # Columna 5 (Wind Speed): ancho 10, alineada izquierda
        # Formato: Metric                  | NWP_GHI | LMD_GHI | Power (MW)| Wind Speed

        nwp = metrics["NWP_GHI"]
        lmd = metrics["LMD_GHI"]
        pwr = metrics["Power"]
        wnd = metrics["Wind Speed"]

        # Ajuste de Power para coincidir con la fila "Nighttime Power > 0     | N/A     | N/A     | X         | N/A"
        # Notar que Power (MW) tiene ancho 11 en el header.
        # "Nighttime Power > 0     | N/A     | N/A     | X         | N/A"
        # Buscamos que los separadores "|" se alineen perfectamente:
        # Longitud de "Metric                  " es 24.
        # "NWP_GHI  " es 9.
        # "LMD_GHI  " es 9.
        # "Power (MW)" es 10 (con 1 espacio extra antes del |).
        # Vamos a replicar el espaciado exacto:
        # "Metric                  | NWP_GHI | LMD_GHI | Power (MW)| Wind Speed"
        # "------------------------------------------------------------------------------"
        # "Null Values             | X       | X       | X         | X"
        # "Negative Values         | X       | X       | X         | X"
        # "Nighttime Power > 0     | N/A     | N/A     | X         | N/A"
        # "------------------------------------------------------------------------------"
        # "Mean                    | X.X     | X.X     | X.X       | X.X"
        # "Std Dev                 | X.X     | X.X     | X.X       | X.X"
        # "Min                     | X.X     | X.X     | X.X       | X.X"
        # "Max                     | X.X     | X.X     | X.X       | X.X"

        lines = [
            "==============================================================================",
            "                    PVOD ETL: DATA QUALITY & PROFILING REPORT",
            "==============================================================================",
            f"Phase:              {phase_name:<12} | Total Records:              {total_records}",
            f"Timestamp Range: {min_date} - {max_date} | Execution Time:             {execution_time:.4f}s",
            "==============================================================================",
            "Metric                  | NWP_GHI | LMD_GHI | Power (MW)| Wind Speed",
            "------------------------------------------------------------------------------",
            f"Null Values             | {nwp['nulls']:<7} | {lmd['nulls']:<7} | {pwr['nulls']:<9} | {wnd['nulls']}",
            f"Negative Values         | {nwp['negatives']:<7} | {lmd['negatives']:<7} | {pwr['negatives']:<9} | {wnd['negatives']}",
            f"Nighttime Power > 0     | N/A     | N/A     | {pwr['nighttime']:<9} | N/A",
            "------------------------------------------------------------------------------",
            f"Mean                    | {nwp['mean']:<7} | {lmd['mean']:<7} | {pwr['mean']:<9} | {wnd['mean']}",
            f"Std Dev                 | {nwp['std']:<7} | {lmd['std']:<7} | {pwr['std']:<9} | {wnd['std']}",
            f"Min                     | {nwp['min']:<7} | {lmd['min']:<7} | {pwr['min']:<9} | {wnd['min']}",
            f"Max                     | {nwp['max']:<7} | {lmd['max']:<7} | {pwr['max']:<9} | {wnd['max']}",
            "==============================================================================",
            f"Overall Quality Score: {overall_score:.1f}%",
            "==============================================================================",
        ]

        return "\n".join(lines)
