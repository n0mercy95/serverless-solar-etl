"""
strategies/nighttime_zeroing_strategy.py — Zeroing Nocturno por Elevación Solar
=================================================================================
Implementación concreta de ``SolarDataCleaningStrategy`` que calcula la
elevación del ángulo solar para cada timestamp y fuerza irradiancia y
salida de potencia a **cero exacto** cuando el sol está bajo el horizonte.

Algoritmo (fórmula astronómica simplificada):
  1. Declinación solar: δ = 23.45° × sin(360/365 × (284 + día_del_año))
  2. Ángulo horario: ω = 15° × (hora + minuto/60 - 12)
  3. Elevación solar: α = arcsin(sin(lat)×sin(δ) + cos(lat)×cos(δ)×cos(ω))
  4. Si α ≤ 0°, forzar columnas de irradiancia y potencia a 0.0

Referencia PRD §3:
  NighttimeZeroingStrategy: Cálculo de elevación de ángulo solar para
  forzar irradiancia y salida de potencia exactamente a cero entre la
  puesta y salida del sol.
"""

from __future__ import annotations

import logging
import math

import polars as pl

from app.application.cleaning_strategy_port import SolarDataCleaningStrategy
from app.domain.constants import (
    DEFAULT_STATION_LATITUDE,
    NIGHTTIME_ZEROING_COLUMNS,
    SOLAR_DECLINATION_AMPLITUDE,
    TEMPORAL_COLUMN,
)

logger = logging.getLogger(__name__)


class NighttimeZeroingStrategy(SolarDataCleaningStrategy):
    """Fuerza irradiancia y potencia a cero durante horas nocturnas.

    Calcula la elevación solar usando la posición astronómica simplificada
    y aplica zeroing vectorizado con expresiones Polars (sin loops Python).

    Parameters
    ----------
    latitude_deg : float, optional
        Latitud de la estación en grados (default: 38.0° para Hebei, China).
    """

    def __init__(self, *, latitude_deg: float = DEFAULT_STATION_LATITUDE) -> None:
        self._latitude_rad = math.radians(latitude_deg)
        self._latitude_deg = latitude_deg

    # ── Contrato ABC ──────────────────────────────────────────────────

    def apply_cleaning(self, dataframe: pl.DataFrame) -> pl.DataFrame:
        """Calcula elevación solar y fuerza zeroing nocturno.

        Parameters
        ----------
        dataframe : pl.DataFrame
            DataFrame con columna ``date_time`` de tipo ``pl.Datetime``.

        Returns
        -------
        pl.DataFrame
            DataFrame con irradiancia/potencia forzadas a 0.0 de noche.
        """
        logger.info(
            "Aplicando NighttimeZeroingStrategy",
            extra={
                "attributes": {
                    "latitude_deg": self._latitude_deg,
                    "columns_affected": list(NIGHTTIME_ZEROING_COLUMNS),
                },
            },
        )

        # ── 1. Calcular elevación solar (vectorizado) ─────────────────
        lat_rad = self._latitude_rad
        decl_amplitude = SOLAR_DECLINATION_AMPLITUDE

        dataframe = dataframe.with_columns(
            # Día del año (1–366)
            pl.col(TEMPORAL_COLUMN).dt.ordinal_day().alias("_day_of_year"),
            # Hora decimal (ej. 14:30 → 14.5)
            (
                pl.col(TEMPORAL_COLUMN).dt.hour()
                + pl.col(TEMPORAL_COLUMN).dt.minute() / 60.0
            ).alias("_hour_decimal"),
        )

        dataframe = dataframe.with_columns(
            # Declinación solar (en radianes)
            (
                math.radians(decl_amplitude)
                * (
                    (2.0 * math.pi / 365.0 * (284.0 + pl.col("_day_of_year")))
                    .sin()
                )
            ).alias("_declination_rad"),
            # Ángulo horario (en radianes)
            (
                math.radians(15.0) * (pl.col("_hour_decimal") - 12.0)
            ).alias("_hour_angle_rad"),
        )

        dataframe = dataframe.with_columns(
            # Elevación solar: α = arcsin(sin(lat)sin(δ) + cos(lat)cos(δ)cos(ω))
            (
                math.sin(lat_rad) * pl.col("_declination_rad").sin()
                + math.cos(lat_rad)
                * pl.col("_declination_rad").cos()
                * pl.col("_hour_angle_rad").cos()
            )
            .arcsin()
            .alias("_solar_elevation_rad"),
        )

        # ── 2. Aplicar zeroing donde elevación ≤ 0 ───────────────────
        is_nighttime = pl.col("_solar_elevation_rad") <= 0.0

        # Contar registros nocturnos para logging
        nighttime_count = dataframe.filter(is_nighttime).height

        zeroing_exprs = [
            pl.when(is_nighttime)
            .then(pl.lit(0.0))
            .otherwise(pl.col(col))
            .alias(col)
            for col in NIGHTTIME_ZEROING_COLUMNS
        ]

        dataframe = dataframe.with_columns(zeroing_exprs)

        # ── 3. Eliminar columnas auxiliares ────────────────────────────
        dataframe = dataframe.drop(
            "_day_of_year",
            "_hour_decimal",
            "_declination_rad",
            "_hour_angle_rad",
            "_solar_elevation_rad",
        )

        logger.info(
            "NighttimeZeroingStrategy completada",
            extra={
                "attributes": {
                    "total_rows": dataframe.height,
                    "nighttime_rows_zeroed": nighttime_count,
                    "nighttime_percentage": round(
                        nighttime_count / max(dataframe.height, 1) * 100, 1
                    ),
                },
            },
        )

        return dataframe
