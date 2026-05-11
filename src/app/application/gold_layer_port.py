"""
application/gold_layer_port.py — Contrato Abstracto de Exportación (Capa Oro)
===============================================================================
Define el puerto ``GoldLayerExportPort`` que toda implementación concreta
de exportación a la capa Gold debe cumplir.  Siguiendo Clean Architecture,
este puerto reside en la capa de Application y **no** conoce detalles de
infraestructura (GCS, paths en disco, etc.).

Referencia PRD §2:
  Almacenamiento Intermedio (Cloud Storage): Actúa como buffer (nivel
  oro/gold layer) alojando temporalmente los datos serializados en
  formato binario Apache Parquet antes de su ingesta a BigQuery.

Referencia PRD §4:
  Exportar de Polars obligatoriamente a formato Apache Parquet
  (con compresión RLE y diccionarios) antes de realizar el Load Job
  masivo a BigQuery.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import polars as pl


class GoldLayerExportPort(ABC):
    """Puerto abstracto para la exportación del DataFrame limpio a la Capa Oro.

    Cada implementación concreta debe:
    1. Aplicar enforcement de tipos finales sobre el DataFrame.
    2. Serializar a formato Apache Parquet con compresión.
    3. Subir el archivo binario al almacenamiento de la Capa Oro.
    4. Retornar el URI del objeto almacenado.
    """

    @abstractmethod
    def export_to_gold_layer(self, dataframe: pl.DataFrame) -> str:
        """Exporta el DataFrame limpio a Parquet y lo sube a la Capa Oro.

        Parameters
        ----------
        dataframe : pl.DataFrame
            DataFrame PVOD limpio (post pipeline de estrategias),
            con todos los tipos ya casteados.

        Returns
        -------
        str
            URI del objeto almacenado en la Capa Oro.
            Formato esperado: ``gs://bucket/gold/pvod_YYYYMMDD_HHMMSS.parquet``

        Raises
        ------
        DataTransformationError
            Si el DataFrame no cumple el esquema final esperado.
        SolarETLError
            Si ocurre un error durante la serialización o el upload.
        """
        ...
