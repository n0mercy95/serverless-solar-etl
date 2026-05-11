"""
application/cleaning_pipeline.py — Orquestador del Pipeline de Limpieza
========================================================================
Ejecuta una cadena ordenada de ``SolarDataCleaningStrategy`` sobre un
``pl.DataFrame`` materializado.  El orden de ejecución importa:

  1. NighttimeZeroingStrategy  — Define la forma física del ciclo diurno.
  2. HampelFilterStrategy      — Filtra anomalías en datos ya formados.
  3. MissingValueImputerStrategy — Interpola gaps sobre datos ya limpios.

Este orquestador reside en la capa de Application porque coordina
casos de uso sin conocer los detalles de cada estrategia concreta.
"""

from __future__ import annotations

import logging
from typing import Sequence

import polars as pl

from app.application.cleaning_strategy_port import SolarDataCleaningStrategy
from app.domain.exceptions import DataTransformationError

logger = logging.getLogger(__name__)


class CleaningPipelineExecutor:
    """Ejecuta una cadena ordenada de estrategias de limpieza.

    Parameters
    ----------
    strategies : Sequence[SolarDataCleaningStrategy]
        Lista de estrategias en orden de ejecución.  Cada estrategia
        recibe el DataFrame producido por la anterior.
    """

    def __init__(self, strategies: Sequence[SolarDataCleaningStrategy]) -> None:
        self._strategies = strategies

    def execute(self, dataframe: pl.DataFrame) -> pl.DataFrame:
        """Aplica cada estrategia en orden secuencial.

        Parameters
        ----------
        dataframe : pl.DataFrame
            DataFrame PVOD materializado (post Tarea 2.1).

        Returns
        -------
        pl.DataFrame
            DataFrame con todas las limpiezas aplicadas.

        Raises
        ------
        DataTransformationError
            Si alguna estrategia falla durante su ejecución.
        """
        initial_rows = dataframe.height

        logger.info(
            "Iniciando pipeline de limpieza",
            extra={
                "attributes": {
                    "strategies_count": len(self._strategies),
                    "initial_rows": initial_rows,
                    "strategy_order": [
                        type(s).__name__ for s in self._strategies
                    ],
                },
            },
        )

        for strategy in self._strategies:
            strategy_name = type(strategy).__name__

            try:
                logger.info(
                    f"Ejecutando estrategia: {strategy_name}",
                    extra={"attributes": {"strategy": strategy_name}},
                )

                dataframe = strategy.apply_cleaning(dataframe)

                logger.info(
                    f"Estrategia {strategy_name} completada",
                    extra={
                        "attributes": {
                            "strategy": strategy_name,
                            "rows_after": dataframe.height,
                        },
                    },
                )

            except DataTransformationError:
                # Re-raise excepciones del dominio sin envolver
                raise
            except Exception as exc:
                raise DataTransformationError(
                    f"Error inesperado en estrategia {strategy_name}: {exc}"
                ) from exc

        logger.info(
            "Pipeline de limpieza completado exitosamente",
            extra={
                "attributes": {
                    "initial_rows": initial_rows,
                    "final_rows": dataframe.height,
                    "strategies_applied": len(self._strategies),
                },
            },
        )

        return dataframe
