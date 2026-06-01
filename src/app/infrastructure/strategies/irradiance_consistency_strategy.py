"""
strategies/irradiance_consistency_strategy.py — Consistencia de Irradiancia Local
===================================================================================
Implementación concreta de ``SolarDataCleaningStrategy`` que detecta y corrige
registros donde la irradiancia difusa local medida es mayor que la irradiancia
global horizontal total (físicamente imposible). Si ocurre, fija ambas a null.
"""

from __future__ import annotations

import logging

import polars as pl

from app.application.cleaning_strategy_port import SolarDataCleaningStrategy

logger = logging.getLogger(__name__)


class IrradianceConsistencyStrategy(SolarDataCleaningStrategy):
    """Valida la consistencia física entre irradiancia difusa y global total local.

    Si lmd_diffuseirrad > lmd_totalirrad, se consideran lecturas corruptas
    y se fijan ambas columnas a null de manera vectorizada para su imputación.
    """

    def apply_cleaning(self, dataframe: pl.DataFrame) -> pl.DataFrame:
        """Aplica la validación de consistencia de irradiancia local.

        Parameters
        ----------
        dataframe : pl.DataFrame
            DataFrame PVOD materializado.

        Returns
        -------
        pl.DataFrame
            DataFrame con violaciones físicas nullificadas.
        """
        logger.info("Aplicando IrradianceConsistencyStrategy")

        # Criterio: difusa > total (excluyendo pre-existentes nulos)
        is_invalid = (
            (pl.col("lmd_diffuseirrad") > pl.col("lmd_totalirrad"))
            & pl.col("lmd_diffuseirrad").is_not_null()
            & pl.col("lmd_totalirrad").is_not_null()
        )

        violations_count = dataframe.filter(is_invalid).height
        if violations_count > 0:
            logger.warning(
                f"IrradianceConsistency: {violations_count} violaciones físicas detectadas. "
                "Fijando lmd_diffuseirrad y lmd_totalirrad a null."
            )

        # Vectorización mutua simultánea
        dataframe = dataframe.with_columns(
            pl.when(is_invalid)
            .then(pl.lit(None, dtype=pl.Float64))
            .otherwise(pl.col("lmd_diffuseirrad"))
            .alias("lmd_diffuseirrad"),
            pl.when(is_invalid)
            .then(pl.lit(None, dtype=pl.Float64))
            .otherwise(pl.col("lmd_totalirrad"))
            .alias("lmd_totalirrad"),
        )

        logger.info(
            "IrradianceConsistencyStrategy completada",
            extra={
                "attributes": {
                    "violations_nullified": violations_count,
                    "total_rows": dataframe.height,
                },
            },
        )

        return dataframe
