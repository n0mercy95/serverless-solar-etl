"""
infrastructure/sciencedb_extractor.py — Extractor de Contingencia vía ScienceDB
=================================================================================
Implementación concreta de ``PVODExtractionPipeline`` que descarga el
CSV PVOD desde la API HTTP de ScienceDB (``scidb.cn``) como fuente
de contingencia/fallback.

Referencia PRD §3:
  ScienceDBHttpExtractor (contingencia/fallback vía API HTTP directa).

Nota: scidb.cn no cuenta con API pública de descarga directa verificada.
Este extractor está implementado completo y funcional para cuando se
disponga de una URL válida.  En la práctica, el ExtractionFactory
intentará GitHub Raw primero.
"""

from __future__ import annotations

import io
import logging

import httpx

from app.application.ports import PVODExtractionPipeline
from app.domain.exceptions import DataSourceUnavailableError, DataValidationError

logger = logging.getLogger(__name__)

# ── Constantes ────────────────────────────────────────────────────────
_DEFAULT_TIMEOUT_SECONDS = 180  # Más tolerante: scidb.cn puede ser lento
_CHUNK_SIZE = 65_536  # 64 KB por iteración de streaming


class ScienceDBHttpExtractor(PVODExtractionPipeline):
    """Descarga el CSV PVOD desde ScienceDB (fuente de contingencia).

    Mismo contrato y misma mecánica de streaming que ``GitHubRawExtractor``,
    pero apuntando a la URL de fallback configurada.

    Parameters
    ----------
    source_url : str
        URL completa al dataset PVOD en ``scidb.cn``.
    timeout : int, optional
        Segundos máximos para la conexión + lectura (default: 180).
    """

    def __init__(self, source_url: str, *, timeout: int = _DEFAULT_TIMEOUT_SECONDS) -> None:
        self._source_url = source_url
        self._timeout = timeout

    # ── Contrato ABC ──────────────────────────────────────────────
    def extract_data_to_buffer(self) -> io.BytesIO:
        """Descarga el CSV vía HTTP streaming y retorna un buffer en memoria.

        Returns
        -------
        io.BytesIO
            Buffer con el CSV completo, posición en 0.

        Raises
        ------
        DataSourceUnavailableError
            Error de red o status HTTP != 200.
        DataValidationError
            Respuesta vacía (0 bytes).
        """
        logger.info(
            "Iniciando extracción de contingencia desde ScienceDB",
            extra={"attributes": {"source_url": self._source_url}},
        )

        buffer = io.BytesIO()

        try:
            with httpx.Client(timeout=self._timeout, follow_redirects=True) as client:
                with client.stream("GET", self._source_url) as response:
                    response.raise_for_status()

                    bytes_downloaded = 0
                    for chunk in response.iter_bytes(chunk_size=_CHUNK_SIZE):
                        buffer.write(chunk)
                        bytes_downloaded += len(chunk)

        except httpx.HTTPStatusError as exc:
            raise DataSourceUnavailableError(
                f"ScienceDB respondió con status {exc.response.status_code} "
                f"para URL: {self._source_url}"
            ) from exc
        except httpx.RequestError as exc:
            raise DataSourceUnavailableError(
                f"Error de red al conectar con ScienceDB: {exc}"
            ) from exc

        # ── Validación post-descarga ──────────────────────────────
        total_bytes = buffer.tell()
        if total_bytes == 0:
            raise DataValidationError(
                "El buffer descargado desde ScienceDB está vacío (0 bytes)."
            )

        buffer.seek(0)

        size_mb = total_bytes / (1024 * 1024)
        logger.info(
            "Extracción de contingencia desde ScienceDB completada",
            extra={
                "attributes": {
                    "source": "sciencedb",
                    "bytes_downloaded": total_bytes,
                    "size_mb": round(size_mb, 2),
                },
            },
        )

        return buffer
