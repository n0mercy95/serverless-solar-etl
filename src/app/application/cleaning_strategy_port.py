"""
application/cleaning_strategy_port.py — Contrato Abstracto de Limpieza (Strategy)
===================================================================================
Define la interfaz ``SolarDataCleaningStrategy`` que toda estrategia
concreta de limpieza de datos fotovoltaicos debe implementar.

Siguiendo Clean Architecture, este puerto reside en la capa de Application.
Las implementaciones concretas (HampelFilter, NighttimeZeroing,
MissingValueImputer) viven en la capa de Infrastructure.

Referencia PRD §3 — Patrón Strategy (Limpieza de Datos Fotovoltaicos):
  Contrato: Interfaz SolarDataCleaningStrategy(ABC) con el método
  apply_cleaning(dataframe).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import polars as pl


class SolarDataCleaningStrategy(ABC):
    """Interfaz del Patrón Strategy para limpieza de datos fotovoltaicos.

    Cada implementación concreta encapsula un algoritmo específico de
    purga heurística.  El ``CleaningPipelineExecutor`` itera sobre una
    secuencia de estrategias aplicándolas en orden.

    El contrato opera sobre ``pl.DataFrame`` (eager) porque operaciones
    como rolling windows (Hampel) y cálculos trigonométricos (elevación
    solar) requieren materialización completa de los datos.
    """

    @abstractmethod
    def apply_cleaning(self, dataframe: pl.DataFrame) -> pl.DataFrame:
        """Aplica la estrategia de limpieza y retorna el DataFrame modificado.

        Parameters
        ----------
        dataframe : pl.DataFrame
            DataFrame PVOD materializado con timestamps alineados,
            tipos estrictos y columnas delta (producido por la Tarea 2.1).

        Returns
        -------
        pl.DataFrame
            DataFrame con la limpieza aplicada.  Debe conservar el mismo
            esquema de columnas (no eliminar ni renombrar columnas).

        Raises
        ------
        DataTransformationError
            Si ocurre un error durante la aplicación de la estrategia.
        """
        ...
