"""
application/ports.py — Contratos Abstractos de Extracción (Puertos)
====================================================================
Define el contrato ``PVODExtractionPipeline`` que toda implementación
concreta de ingesta debe cumplir.  Siguiendo Clean Architecture, este
puerto reside en la capa de Application y **no** conoce detalles de
infraestructura (HTTP, GCS, etc.).

Referencia PRD §3 — Patrón Factory (Ingesta):
  Contrato: Crear clase PVODExtractionPipeline(ABC) con el método
  @abstractmethod extract_data_to_buffer().
"""

from __future__ import annotations

import io
from abc import ABC, abstractmethod


class PVODExtractionPipeline(ABC):
    """Puerto abstracto para la extracción del dataset PVOD.

    Cada implementación concreta (GitHubRawExtractor, ScienceDBHttpExtractor)
    debe proveer la lógica de descarga HTTP y retornar el contenido CSV
    como un buffer binario en memoria (``io.BytesIO``).
    """

    @abstractmethod
    def extract_data_to_buffer(self) -> io.BytesIO:
        """Descarga el CSV PVOD y lo retorna como buffer binario en memoria.

        Returns
        -------
        io.BytesIO
            Buffer binario con el contenido completo del CSV descargado,
            con la posición del cursor en 0 (listo para lectura).

        Raises
        ------
        DataSourceUnavailableError
            Si la fuente HTTP no responde o devuelve un status inesperado.
        DataValidationError
            Si el contenido descargado está vacío o es inválido.
        """
        ...
