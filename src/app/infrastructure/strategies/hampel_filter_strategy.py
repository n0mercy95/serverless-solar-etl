"""
strategies/hampel_filter_strategy.py — Filtro Hampel para Anomalías de Viento
===============================================================================
Implementación concreta de ``SolarDataCleaningStrategy`` que aplica el
filtro Hampel (basado en Median Absolute Deviation de ventana móvil) para
detectar y corregir anomalías en las columnas de velocidad del viento.

Algoritmo por columna:
  1. rolling_median = col.rolling_median(window_size)
  2. deviation = |col - rolling_median|
  3. rolling_mad = deviation.rolling_median(window_size)
  4. is_outlier = deviation > threshold × consistency_factor × rolling_mad
  5. cleaned = when(is_outlier).then(rolling_median).otherwise(col)

Referencia PRD §3:
  HampelFilterStrategy: Filtro por desviación absoluta mediana de ventana
  móvil para anomalías en la velocidad del viento.
"""

from __future__ import annotations

import logging

import polars as pl

from app.application.cleaning_strategy_port import SolarDataCleaningStrategy
from app.domain.constants import (
    HAMPEL_CONSISTENCY_FACTOR,
    HAMPEL_THRESHOLD,
    HAMPEL_WINDOW_SIZE,
    WIND_SPEED_COLUMNS,
)

logger = logging.getLogger(__name__)


class HampelFilterStrategy(SolarDataCleaningStrategy):
    """Filtro Hampel para detección y corrección de outliers en viento.

    Utiliza la Median Absolute Deviation (MAD) como estimador robusto
    de dispersión.  Los outliers se reemplazan con la mediana móvil,
    preservando la estructura temporal de la serie.

    Parameters
    ----------
    window_size : int, optional
        Tamaño de la ventana móvil en registros (default: 5).
    threshold : float, optional
        Umbral en MADs escaladas para clasificar outliers (default: 3.0).
    """

    def __init__(
        self,
        *,
        window_size: int = HAMPEL_WINDOW_SIZE,
        threshold: float = HAMPEL_THRESHOLD,
    ) -> None:
        self._window_size = window_size
        self._threshold = threshold
        self._consistency_factor = HAMPEL_CONSISTENCY_FACTOR

    # ── Contrato ABC ──────────────────────────────────────────────────

    def apply_cleaning(self, dataframe: pl.DataFrame) -> pl.DataFrame:
        """Aplica el filtro Hampel a las columnas de velocidad de viento.

        Parameters
        ----------
        dataframe : pl.DataFrame
            DataFrame con columnas de velocidad de viento.

        Returns
        -------
        pl.DataFrame
            DataFrame con outliers reemplazados por la mediana móvil.
        """
        logger.info(
            "Aplicando HampelFilterStrategy",
            extra={
                "attributes": {
                    "window_size": self._window_size,
                    "threshold": self._threshold,
                    "columns": list(WIND_SPEED_COLUMNS),
                },
            },
        )

        total_outliers = 0

        for col_name in WIND_SPEED_COLUMNS:
            dataframe, outlier_count = self._apply_hampel_to_column(
                dataframe, col_name
            )
            total_outliers += outlier_count

        logger.info(
            "HampelFilterStrategy completada",
            extra={
                "attributes": {
                    "total_outliers_replaced": total_outliers,
                    "total_rows": dataframe.height,
                    "outlier_percentage": round(
                        total_outliers / max(dataframe.height * len(WIND_SPEED_COLUMNS), 1) * 100,
                        3,
                    ),
                },
            },
        )

        return dataframe

    # ── Métodos Internos ──────────────────────────────────────────────

    def _apply_hampel_to_column(
        self, df: pl.DataFrame, col_name: str
    ) -> tuple[pl.DataFrame, int]:
        """Aplica el filtro Hampel a una columna específica.

        Parameters
        ----------
        df : pl.DataFrame
            DataFrame fuente.
        col_name : str
            Nombre de la columna a filtrar.

        Returns
        -------
        tuple[pl.DataFrame, int]
            Tupla de (DataFrame con columna limpia, cantidad de outliers).

        Notes
        -----
        Se usa ``min_samples=1`` para que ventanas parciales en los
        extremos de la serie generen valores en lugar de ``null``.
        Cuando la MAD = 0 (datos perfectamente homogéneos), se aplica
        un floor mínimo para evitar falsos negativos en outliers obvios.
        """
        window = self._window_size
        threshold = self._threshold
        k = self._consistency_factor

        # ── 1. Calcular mediana móvil ─────────────────────────────────
        df = df.with_columns(
            pl.col(col_name)
            .rolling_median(window_size=window, center=True, min_samples=1)
            .alias("_rolling_median")
        )

        # ── 2. Calcular desviación absoluta respecto a la mediana ─────
        df = df.with_columns(
            (pl.col(col_name) - pl.col("_rolling_median"))
            .abs()
            .alias("_abs_deviation")
        )

        # ── 3. Calcular MAD móvil (mediana de las desviaciones) ───────
        # Floor en 1e-10 para evitar MAD=0 que causaría falsos negativos
        df = df.with_columns(
            pl.col("_abs_deviation")
            .rolling_median(window_size=window, center=True, min_samples=1)
            .clip(lower_bound=1e-10)
            .alias("_rolling_mad")
        )

        # ── 4. Marcar outliers: |x - median| > threshold × k × MAD ───
        df = df.with_columns(
            (
                pl.col("_abs_deviation")
                > (threshold * k * pl.col("_rolling_mad"))
            ).alias("_is_outlier")
        )

        # Contar outliers antes de reemplazar
        outlier_count = df.filter(pl.col("_is_outlier")).height

        if outlier_count > 0:
            logger.info(
                f"Hampel: {outlier_count} outliers en '{col_name}'",
                extra={
                    "attributes": {
                        "column": col_name,
                        "outliers_found": outlier_count,
                    },
                },
            )

        # ── 5. Reemplazar outliers con la mediana móvil ───────────────
        df = df.with_columns(
            pl.when(pl.col("_is_outlier"))
            .then(pl.col("_rolling_median"))
            .otherwise(pl.col(col_name))
            .alias(col_name)
        )

        # ── 6. Limpiar columnas auxiliares ────────────────────────────
        df = df.drop(
            "_rolling_median",
            "_abs_deviation",
            "_rolling_mad",
            "_is_outlier",
        )

        return df, outlier_count

