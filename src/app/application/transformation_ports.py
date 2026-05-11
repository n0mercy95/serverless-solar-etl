"""
application/transformation_ports.py — Contrato Abstracto de Transformación
===========================================================================
Define el puerto ``PVODTransformationPipeline`` que toda implementación
de carga lazy y alineamiento temporal debe cumplir.  Siguiendo Clean
Architecture, este puerto reside en la capa de Application y **no**
conoce detalles de infraestructura (rutas en disco, tempfiles, etc.).

Referencia PRD §6 — Fase 2, Tarea 2.1:
  Carga perezosa (lazy query vía scan_csv) en entorno Polars.
  Ejecución de Joins temporales alineados cada 15 minutos exactos
  para cruzar matrices LMD y NWP.
"""

from __future__ import annotations

import io
from abc import ABC, abstractmethod

import polars as pl


class PVODTransformationPipeline(ABC):
    """Puerto abstracto para la carga lazy y alineamiento temporal del PVOD.

    Cada implementación concreta debe:
    1. Recibir un buffer binario con el CSV crudo.
    2. Construir un ``LazyFrame`` optimizado vía ``scan_csv``.
    3. Parsear y normalizar timestamps a la grilla de 15 minutos.
    4. Validar integridad temporal y restricciones físicas.
    5. Retornar un ``LazyFrame`` listo para la fase de limpieza (Strategy).
    """

    @abstractmethod
    def load_and_align(self, buffer: io.BytesIO) -> pl.LazyFrame:
        """Carga el CSV desde un buffer en modo lazy y ejecuta el
        alineamiento temporal a la grilla estricta de 15 minutos.

        Parameters
        ----------
        buffer : io.BytesIO
            Buffer binario con el contenido del CSV PVOD consolidado,
            posición del cursor en 0 (producido por la fase de extracción).

        Returns
        -------
        pl.LazyFrame
            LazyFrame con:
            - ``date_time`` parseado a ``pl.Datetime`` y truncado a 15 min.
            - Todas las columnas numéricas casteadas a ``Float64``.
            - ``station_id`` casteado a ``UInt8``.
            - Columnas delta NWP-LMD calculadas.
            - Validaciones de integridad temporal y física ejecutadas.

        Raises
        ------
        TemporalAlignmentError
            Si se detectan duplicados, gaps o timestamps desalineados.
        IrradianceOutOfBoundsError
            Si alguna columna de irradiancia viola las restricciones físicas.
        DataTransformationError
            Fallo genérico durante la transformación.
        """
        ...
