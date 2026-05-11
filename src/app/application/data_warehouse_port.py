"""
application/data_warehouse_port.py — Contrato de Data Warehouse
=================================================================
Define el puerto ``DataWarehouseRepository(ABC)`` que será
implementado por el adaptador en la capa de Infraestructura.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class DataWarehouseRepository(ABC):
    """Puerto abstracto para la integración transaccional con el Data Warehouse.

    Define la interfaz exigida por la capa de Aplicación para
    ejecutar inserciones analíticas de forma idempotente.
    """

    @abstractmethod
    def load_dataframe_idempotent(self, gcs_uri: str) -> str:
        """Inicia una carga idempotente desde una URI de Capa Oro al Warehouse.

        Parameters
        ----------
        gcs_uri : str
            URI completa del archivo Parquet en la Capa Oro
            (ej. ``gs://bucket/gold/pvod_123.parquet``).

        Returns
        -------
        str
            Identificador determinista (MD5) del trabajo de carga (job_id).

        Raises
        ------
        BigQueryConnectionError
            Si el Load Job falla, la configuración no es válida
            o no hay conectividad con la plataforma cloud.
        """
        ...
