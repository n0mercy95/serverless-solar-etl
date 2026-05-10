"""
infrastructure/github_extractor.py — Extractor Primario vía GitHub Raw
=======================================================================
Implementación concreta de ``PVODExtractionPipeline`` que descarga el
CSV consolidado PVOD desde ``raw.githubusercontent.com`` usando
streaming HTTP para controlar el uso de memoria.

Referencia PRD §3:
  GitHubRawExtractor (prioritario vía raw requests a
  raw.githubusercontent.com).
"""

from __future__ import annotations

import io
import logging

import httpx

from app.application.ports import PVODExtractionPipeline
from app.domain.exceptions import DataSourceUnavailableError, DataValidationError

logger = logging.getLogger(__name__)

# ── Constantes ────────────────────────────────────────────────────────
_DEFAULT_TIMEOUT_SECONDS = 120
_CHUNK_SIZE = 65_536  # 64 KB por iteración de streaming


class GitHubRawExtractor(PVODExtractionPipeline):
    """Descarga el CSV PVOD desde GitHub Raw Content (fuente primaria).

    Utiliza ``httpx.Client`` con streaming para evitar cargar la respuesta
    HTTP completa en memoria antes de escribirla al buffer ``io.BytesIO``.

    Parameters
    ----------
    source_url : str
        URL completa al archivo CSV en ``raw.githubusercontent.com``.
    timeout : int, optional
        Segundos máximos para la conexión + lectura (default: 120).
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
            "Iniciando extracción desde GitHub Raw",
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
                f"GitHub Raw respondió con status {exc.response.status_code} "
                f"para URL: {self._source_url}"
            ) from exc
        except httpx.RequestError as exc:
            raise DataSourceUnavailableError(
                f"Error de red al conectar con GitHub Raw: {exc}"
            ) from exc

        # ── Validación post-descarga ──────────────────────────────
        total_bytes = buffer.tell()
        if total_bytes == 0:
            raise DataValidationError(
                "El buffer descargado desde GitHub Raw está vacío (0 bytes)."
            )

        buffer.seek(0)

        size_mb = total_bytes / (1024 * 1024)
        logger.info(
            "Extracción desde GitHub Raw completada",
            extra={
                "attributes": {
                    "source": "github_raw",
                    "bytes_downloaded": total_bytes,
                    "size_mb": round(size_mb, 2),
                },
            },
        )

        return buffer
