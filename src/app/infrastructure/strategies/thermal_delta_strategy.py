"""
strategies/thermal_delta_strategy.py — Desviación Térmica Cruzada
===================================================================
Implementación concreta de ``SolarDataCleaningStrategy`` que detecta y corrige
desviaciones térmicas absurdas (mayores a 15°C) entre el pronóstico NWP y el
sensor local LMD, asumiendo fallo del hardware local y fijándolo a null.
"""

from __future__ import annotations

import logging

import polars as pl

from app.application.cleaning_strategy_port import SolarDataCleaningStrategy
from app.domain.constants import MAX_THERMAL_DELTA

logger = logging.getLogger(__name__)


class ThermalDeltaStrategy(SolarDataCleaningStrategy):
    """Filtra y purga mediciones de temperatura local desviadas de la predicción.

    Si la diferencia absoluta entre nwp_temperature y lmd_temperature supera
    los 15°C, se asume fallo del sensor local y se fija lmd_temperature a null.
    """

    def apply_cleaning(self, dataframe: pl.DataFrame) -> pl.DataFrame:
        """Aplica la validación de desviación térmica cruzada.

        Parameters
        ----------
        dataframe : pl.DataFrame
            DataFrame PVOD materializado.

        Returns
        -------
        pl.DataFrame
            DataFrame con anomalías del sensor de temperatura local nullificadas.
        """
        logger.info("Aplicando ThermalDeltaStrategy")

        # Criterio: diferencia absoluta > 15 (excluyendo pre-existentes nulos)
        is_invalid = (
            (pl.col("nwp_temperature") - pl.col("lmd_temperature")).abs() > MAX_THERMAL_DELTA
        ) & pl.col("nwp_temperature").is_not_null() & pl.col("lmd_temperature").is_not_null()

        violations_count = dataframe.filter(is_invalid).height
        if violations_count > 0:
            logger.warning(
                f"ThermalDelta: {violations_count} desviaciones térmicas absurdas detectadas. "
                "Fijando lmd_temperature a null."
            )

        # Reemplazar lmd_temperature con null en registros inválidos
        dataframe = dataframe.with_columns(
            pl.when(is_invalid)
            .then(pl.lit(None, dtype=pl.Float64))
            .otherwise(pl.col("lmd_temperature"))
            .alias("lmd_temperature")
        )

        logger.info(
            "ThermalDeltaStrategy completada",
            extra={
                "attributes": {
                    "violations_nullified": violations_count,
                    "total_rows": dataframe.height,
                },
            },
        )

        return dataframe
