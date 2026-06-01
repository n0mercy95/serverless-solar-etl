"""
strategies/thermodynamic_bounds_strategy.py — Estrategia de Límites Termodinámicos
================================================================================
Implementación concreta de ``SolarDataCleaningStrategy`` que detecta e invalida
(fija a null) registros con valores meteorológicos físicamente imposibles.
Filtra humedad fuera de [0, 100], dirección del viento fuera de [0, 360],
y presión atmosférica fuera de [800, 1100] hPa.
"""

from __future__ import annotations

import logging
from typing import Sequence

import polars as pl

from app.application.cleaning_strategy_port import SolarDataCleaningStrategy
from app.domain.constants import (
    HUMIDITY_MAX,
    HUMIDITY_MIN,
    PRESSURE_MAX,
    PRESSURE_MIN,
    WIND_DIRECTION_MAX,
    WIND_DIRECTION_MIN,
)

logger = logging.getLogger(__name__)


class ThermodynamicBoundsStrategy(SolarDataCleaningStrategy):
    """Filtra y purga mediciones fuera de los límites físicos y termodinámicos.

    Los valores que no cumplen con los límites establecidos se reemplazan
    con ``null`` de forma vectorizada, permitiendo que la estrategia
    ``MissingValueImputerStrategy`` los interpole downstream.
    """

    def __init__(self) -> None:
        self._humidity_cols = ["nwp_humidity"]
        self._wind_dir_cols = ["nwp_winddirection", "lmd_winddirection"]
        self._pressure_cols = ["nwp_pressure", "lmd_pressure"]

    def apply_cleaning(self, dataframe: pl.DataFrame) -> pl.DataFrame:
        """Purga registros fuera de los límites termodinámicos y físicos.

        Parameters
        ----------
        dataframe : pl.DataFrame
            DataFrame PVOD materializado.

        Returns
        -------
        pl.DataFrame
            DataFrame con valores fuera de límites reemplazados por ``null``.
        """
        logger.info(
            "Aplicando ThermodynamicBoundsStrategy",
            extra={
                "attributes": {
                    "humidity_bounds": [HUMIDITY_MIN, HUMIDITY_MAX],
                    "wind_direction_bounds": [WIND_DIRECTION_MIN, WIND_DIRECTION_MAX],
                    "pressure_bounds": [PRESSURE_MIN, PRESSURE_MAX],
                },
            },
        )

        total_violations = 0
        exprs = []

        # 1. Validar Humedad (nwp_humidity)
        for col in self._humidity_cols:
            is_valid = pl.col(col).is_between(HUMIDITY_MIN, HUMIDITY_MAX) | pl.col(col).is_null()
            violations = dataframe.filter(~is_valid).height
            total_violations += violations
            if violations > 0:
                logger.warning(
                    f"Thermodynamic: {violations} anomalías detectadas en '{col}'",
                    extra={
                        "attributes": {
                            "column": col,
                            "violations": violations,
                        },
                    },
                )
            exprs.append(
                pl.when(is_valid)
                .then(pl.col(col))
                .otherwise(pl.lit(None, dtype=pl.Float64))
                .alias(col)
            )

        # 2. Validar Dirección del Viento (nwp_winddirection, lmd_winddirection)
        for col in self._wind_dir_cols:
            is_valid = pl.col(col).is_between(WIND_DIRECTION_MIN, WIND_DIRECTION_MAX) | pl.col(col).is_null()
            violations = dataframe.filter(~is_valid).height
            total_violations += violations
            if violations > 0:
                logger.warning(
                    f"Thermodynamic: {violations} anomalías detectadas en '{col}'",
                    extra={
                        "attributes": {
                            "column": col,
                            "violations": violations,
                        },
                    },
                )
            exprs.append(
                pl.when(is_valid)
                .then(pl.col(col))
                .otherwise(pl.lit(None, dtype=pl.Float64))
                .alias(col)
            )

        # 3. Validar Presión Atmosférica (nwp_pressure, lmd_pressure)
        for col in self._pressure_cols:
            is_valid = pl.col(col).is_between(PRESSURE_MIN, PRESSURE_MAX) | pl.col(col).is_null()
            violations = dataframe.filter(~is_valid).height
            total_violations += violations
            if violations > 0:
                logger.warning(
                    f"Thermodynamic: {violations} anomalías detectadas en '{col}'",
                    extra={
                        "attributes": {
                            "column": col,
                            "violations": violations,
                        },
                    },
                )
            exprs.append(
                pl.when(is_valid)
                .then(pl.col(col))
                .otherwise(pl.lit(None, dtype=pl.Float64))
                .alias(col)
            )

        # Aplicar transformaciones vectorizadas
        dataframe = dataframe.with_columns(exprs)

        logger.info(
            "ThermodynamicBoundsStrategy completada",
            extra={
                "attributes": {
                    "total_violations_nullified": total_violations,
                    "total_rows": dataframe.height,
                },
            },
        )

        return dataframe
