"""
strategies/missing_value_imputer_strategy.py — Imputación de Valores Faltantes
================================================================================
Implementación concreta de ``SolarDataCleaningStrategy`` que resuelve
lagunas temporales (valores ``null``) en las columnas numéricas del PVOD.

Algoritmo por estación:
  1. Interpolación lineal (``pl.Expr.interpolate()``) para gaps internos.
  2. Forward-fill para cubrir nulls al inicio de la serie.
  3. Backward-fill para cubrir nulls al final de la serie.

La interpolación se ejecuta **por estación** para evitar interpolar
entre series de estaciones distintas (lo cual sería físicamente inválido).

Referencia PRD §3:
  MissingValueImputerStrategy: Imputación basada en splines o curva base
  de irradiancia teórica extraterrestre para resolver lagunas temporales.

Nota: Se usa interpolación lineal nativa de Polars (performante y
determinista).  Para intervalos de 15 minutos, es una aproximación
excelente de un spline lineal.
"""

from __future__ import annotations

import logging

import polars as pl

from app.application.cleaning_strategy_port import SolarDataCleaningStrategy
from app.domain.constants import (
    IMPUTATION_COLUMNS,
    STATION_COLUMN,
    TEMPORAL_COLUMN,
)

logger = logging.getLogger(__name__)


class MissingValueImputerStrategy(SolarDataCleaningStrategy):
    """Imputa valores faltantes mediante interpolación lineal por estación.

    La estrategia opera por estación (``group_by("station_id")``) para
    respetar la independencia física entre series de distintas estaciones.
    Dentro de cada estación, los datos se ordenan por timestamp antes
    de interpolar.
    """

    # ── Contrato ABC ──────────────────────────────────────────────────

    def apply_cleaning(self, dataframe: pl.DataFrame) -> pl.DataFrame:
        """Imputa nulls en columnas numéricas mediante interpolación.

        Parameters
        ----------
        dataframe : pl.DataFrame
            DataFrame con posibles valores ``null`` en columnas numéricas.

        Returns
        -------
        pl.DataFrame
            DataFrame sin valores ``null`` en las columnas de imputación.
        """
        # Contar nulls antes de imputar
        null_counts_before = self._count_nulls(dataframe)
        total_nulls = sum(null_counts_before.values())

        logger.info(
            "Aplicando MissingValueImputerStrategy",
            extra={
                "attributes": {
                    "total_nulls_before": total_nulls,
                    "null_counts_per_column": null_counts_before,
                },
            },
        )

        if total_nulls == 0:
            logger.info("No se encontraron valores faltantes — sin cambios")
            return dataframe

        # ── Interpolación por estación ────────────────────────────────
        # Ordenar por estación y timestamp para garantizar interpolación
        # temporalmente correcta
        dataframe = dataframe.sort([STATION_COLUMN, TEMPORAL_COLUMN])

        # Construir expresiones de imputación para cada columna
        imputation_exprs = []
        for col_name in IMPUTATION_COLUMNS:
            if col_name in dataframe.columns:
                imputation_exprs.append(
                    pl.col(col_name)
                    .interpolate()
                    .forward_fill()
                    .backward_fill()
                    .alias(col_name)
                )

        # Aplicar imputación dentro de cada grupo de estación
        dataframe = dataframe.with_columns(
            *[
                pl.col(col_name)
                .interpolate()
                .over(STATION_COLUMN)
                .alias(col_name)
                for col_name in IMPUTATION_COLUMNS
                if col_name in dataframe.columns
            ]
        )

        # Forward-fill y backward-fill para extremos (por estación)
        dataframe = dataframe.with_columns(
            *[
                pl.col(col_name)
                .forward_fill()
                .over(STATION_COLUMN)
                .alias(col_name)
                for col_name in IMPUTATION_COLUMNS
                if col_name in dataframe.columns
            ]
        )

        dataframe = dataframe.with_columns(
            *[
                pl.col(col_name)
                .backward_fill()
                .over(STATION_COLUMN)
                .alias(col_name)
                for col_name in IMPUTATION_COLUMNS
                if col_name in dataframe.columns
            ]
        )

        # Verificar resultado
        null_counts_after = self._count_nulls(dataframe)
        remaining_nulls = sum(null_counts_after.values())

        logger.info(
            "MissingValueImputerStrategy completada",
            extra={
                "attributes": {
                    "nulls_before": total_nulls,
                    "nulls_after": remaining_nulls,
                    "nulls_resolved": total_nulls - remaining_nulls,
                },
            },
        )

        return dataframe

    # ── Utilidades ────────────────────────────────────────────────────

    @staticmethod
    def _count_nulls(df: pl.DataFrame) -> dict[str, int]:
        """Cuenta nulls por columna de imputación.

        Returns
        -------
        dict[str, int]
            Mapeo columna → cantidad de nulls (solo columnas con nulls > 0).
        """
        counts = {}
        for col_name in IMPUTATION_COLUMNS:
            if col_name in df.columns:
                n = df[col_name].null_count()
                if n > 0:
                    counts[col_name] = n
        return counts
