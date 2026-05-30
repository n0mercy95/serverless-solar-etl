"""
strategies/irradiance_outlier_strategy.py — Filtro de Outliers NWP vs LMD
==========================================================================
Implementación concreta de ``SolarDataCleaningStrategy`` que detecta y
corrige registros donde la predicción NWP y la medición LMD divergen
excesivamente, indicando fallo de sensor, error de modelo o condiciones
atmosféricas anómalas (sombra parcial, cloud edge enhancement).

Algoritmo:
  1. Para cada par (NWP, LMD), calcular ratio = NWP / LMD.
  2. Aplicar filtro solo donde ambos valores > umbral mínimo (50 W/m²),
     para evitar falsos positivos en amanecer/atardecer.
  3. Si ratio < 0.3 o ratio > 3.0, marcar como outlier.
  4. Reemplazar valores outlier con ``null`` para que la estrategia
     ``MissingValueImputerStrategy`` (downstream) los interpole.

Referencia:
  Los umbrales se derivaron del análisis estadístico del dataset PVOD:
  - Mediana del ratio NWP/LMD: 0.97 (excelente acuerdo)
  - IQR: [0.71, 1.47]
  - Ratio [0.3, 3.0] elimina el ~12.5% de outliers más extremos
"""

from __future__ import annotations

import logging

import polars as pl

from app.application.cleaning_strategy_port import SolarDataCleaningStrategy
from app.domain.constants import (
    IRRADIANCE_OUTLIER_MIN_THRESHOLD,
    IRRADIANCE_OUTLIER_PAIRS,
    IRRADIANCE_OUTLIER_RATIO_HIGH,
    IRRADIANCE_OUTLIER_RATIO_LOW,
)

logger = logging.getLogger(__name__)


class IrradianceOutlierStrategy(SolarDataCleaningStrategy):
    """Filtra registros donde la predicción NWP diverge excesivamente de LMD.

    Los valores outlier se reemplazan con ``null`` para que sean
    interpolados por ``MissingValueImputerStrategy`` en el paso siguiente
    del pipeline de limpieza.

    Parameters
    ----------
    ratio_low : float, optional
        Ratio mínimo aceptable NWP/LMD (default: 0.3).
    ratio_high : float, optional
        Ratio máximo aceptable NWP/LMD (default: 3.0).
    min_threshold : float, optional
        Umbral mínimo de irradiancia para aplicar el filtro (default: 50 W/m²).
    """

    def __init__(
        self,
        *,
        ratio_low: float = IRRADIANCE_OUTLIER_RATIO_LOW,
        ratio_high: float = IRRADIANCE_OUTLIER_RATIO_HIGH,
        min_threshold: float = IRRADIANCE_OUTLIER_MIN_THRESHOLD,
    ) -> None:
        self._ratio_low = ratio_low
        self._ratio_high = ratio_high
        self._min_threshold = min_threshold

    # ── Contrato ABC ──────────────────────────────────────────────────

    def apply_cleaning(self, dataframe: pl.DataFrame) -> pl.DataFrame:
        """Detecta y nullifica outliers de irradiancia NWP vs LMD.

        Parameters
        ----------
        dataframe : pl.DataFrame
            DataFrame con columnas de irradiancia NWP y LMD.

        Returns
        -------
        pl.DataFrame
            DataFrame con outliers de irradiancia reemplazados por ``null``.
        """
        logger.info(
            "Aplicando IrradianceOutlierStrategy",
            extra={
                "attributes": {
                    "ratio_bounds": [self._ratio_low, self._ratio_high],
                    "min_threshold_wm2": self._min_threshold,
                    "pairs": [list(p) for p in IRRADIANCE_OUTLIER_PAIRS],
                },
            },
        )

        total_outliers = 0

        for nwp_col, lmd_col in IRRADIANCE_OUTLIER_PAIRS:
            dataframe, outlier_count = self._filter_pair(
                dataframe, nwp_col, lmd_col
            )
            total_outliers += outlier_count

        logger.info(
            "IrradianceOutlierStrategy completada",
            extra={
                "attributes": {
                    "total_outliers_nullified": total_outliers,
                    "total_rows": dataframe.height,
                    "outlier_percentage": round(
                        total_outliers / max(dataframe.height, 1) * 100, 2
                    ),
                },
            },
        )

        return dataframe

    # ── Métodos Internos ──────────────────────────────────────────────

    def _filter_pair(
        self, df: pl.DataFrame, nwp_col: str, lmd_col: str
    ) -> tuple[pl.DataFrame, int]:
        """Filtra outliers para un par de columnas NWP/LMD.

        Parameters
        ----------
        df : pl.DataFrame
            DataFrame fuente.
        nwp_col : str
            Nombre de la columna NWP.
        lmd_col : str
            Nombre de la columna LMD.

        Returns
        -------
        tuple[pl.DataFrame, int]
            Tupla de (DataFrame con outliers nullificados, cantidad de outliers).
        """
        min_thr = self._min_threshold
        ratio_lo = self._ratio_low
        ratio_hi = self._ratio_high

        # ── Condición: ambos valores por encima del umbral mínimo ─────
        both_significant = (
            (pl.col(nwp_col) > min_thr) & (pl.col(lmd_col) > min_thr)
        )

        # ── Ratio NWP / LMD ──────────────────────────────────────────
        ratio = pl.col(nwp_col) / pl.col(lmd_col)

        # ── Marcar outliers: ratio fuera del rango aceptable ─────────
        is_outlier = both_significant & (
            (ratio < ratio_lo) | (ratio > ratio_hi)
        )

        # Contar outliers
        outlier_count = df.filter(is_outlier).height

        if outlier_count > 0:
            logger.info(
                f"Irradiance outliers: {outlier_count} en par ({nwp_col}, {lmd_col})",
                extra={
                    "attributes": {
                        "nwp_col": nwp_col,
                        "lmd_col": lmd_col,
                        "outliers_found": outlier_count,
                    },
                },
            )

        # ── Reemplazar con null para interpolación downstream ─────────
        df = df.with_columns(
            pl.when(is_outlier)
            .then(pl.lit(None, dtype=pl.Float64))
            .otherwise(pl.col(nwp_col))
            .alias(nwp_col),
            pl.when(is_outlier)
            .then(pl.lit(None, dtype=pl.Float64))
            .otherwise(pl.col(lmd_col))
            .alias(lmd_col),
        )

        return df, outlier_count
