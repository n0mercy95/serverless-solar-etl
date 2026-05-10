"""
application/extraction_factory.py — Factory de Extractores con Fallback
========================================================================
Implementa el Patrón Factory exigido por el PRD §3 para resolver
dinámicamente qué implementación de ``PVODExtractionPipeline`` usar.

La estrategia es secuencial con fallback automático:
  1. Intenta ``GitHubRawExtractor`` (fuente primaria).
  2. Si falla con ``DataExtractionError``, cae a ``ScienceDBHttpExtractor``.
  3. Si ambas fallan, propaga la excepción al caller.

Referencia PRD §3:
  Constructor: ExtractionFactory, que evalúe variables de entorno y
  devuelva dinámicamente el objeto de extracción sin anidar declaraciones.
"""

from __future__ import annotations

import io
import logging
from typing import Sequence

from app.application.config import Settings
from app.application.ports import PVODExtractionPipeline
from app.domain.exceptions import (
    DataExtractionError,
    DataSourceUnavailableError,
)
from app.infrastructure.github_extractor import GitHubRawExtractor
from app.infrastructure.sciencedb_extractor import ScienceDBHttpExtractor

logger = logging.getLogger(__name__)


class ExtractionFactory:
    """Construye y ejecuta la cadena de extractores con fallback automático.

    En lugar de anidar ``if/elif`` para decidir el extractor, se usa una
    secuencia ordenada por prioridad.  El primer extractor que logre
    descargar el CSV gana; los demás se saltan.

    Parameters
    ----------
    settings : Settings
        Configuración validada con las URLs de las fuentes de datos.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _build_extractor_chain(self) -> Sequence[PVODExtractionPipeline]:
        """Construye la cadena ordenada de extractores desde la configuración.

        Returns
        -------
        Sequence[PVODExtractionPipeline]
            Lista de extractores en orden de prioridad (GitHub primero).
        """
        return [
            GitHubRawExtractor(source_url=str(self._settings.github_raw_url)),
            ScienceDBHttpExtractor(source_url=str(self._settings.scidb_fallback_url)),
        ]

    def create_extractor(self) -> PVODExtractionPipeline:
        """Retorna el primer extractor disponible en la cadena de prioridad.

        Intenta instanciar y verificar la disponibilidad de cada extractor
        en orden.  En esta implementación, simplemente retorna el primero
        (GitHub), ya que la verificación real ocurre en ``extract_with_fallback``.

        Returns
        -------
        PVODExtractionPipeline
            Extractor primario (GitHubRawExtractor por defecto).
        """
        chain = self._build_extractor_chain()
        return chain[0]

    def extract_with_fallback(self) -> io.BytesIO:
        """Ejecuta la extracción probando cada fuente en orden de prioridad.

        Este es el método principal que el caso de uso debe invocar.
        Itera sobre la cadena de extractores: si el primero falla con
        ``DataExtractionError``, intenta el siguiente.  Si todos fallan,
        propaga la última excepción.

        Returns
        -------
        io.BytesIO
            Buffer con el CSV descargado exitosamente.

        Raises
        ------
        DataSourceUnavailableError
            Si ninguna fuente de datos logró responder exitosamente.
        """
        chain = self._build_extractor_chain()
        last_error: DataExtractionError | None = None

        for extractor in chain:
            extractor_name = type(extractor).__name__
            try:
                logger.info(
                    f"Intentando extracción con {extractor_name}",
                    extra={"attributes": {"extractor": extractor_name}},
                )
                buffer = extractor.extract_data_to_buffer()
                logger.info(
                    f"Extracción exitosa con {extractor_name}",
                    extra={
                        "attributes": {
                            "extractor": extractor_name,
                            "buffer_size_bytes": buffer.getbuffer().nbytes,
                        },
                    },
                )
                return buffer

            except DataExtractionError as exc:
                logger.warning(
                    f"Fallo en {extractor_name}, intentando siguiente fuente",
                    extra={
                        "attributes": {
                            "extractor": extractor_name,
                            "error": str(exc),
                        },
                    },
                )
                last_error = exc

        # Si llegamos aquí, todas las fuentes fallaron
        raise DataSourceUnavailableError(
            "Todas las fuentes de datos fallaron. "
            f"Último error: {last_error}"
        ) from last_error
