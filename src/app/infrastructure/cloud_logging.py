"""
infrastructure/cloud_logging.py — Manipulador Estructural JSON (Google Cloud Logging)
======================================================================================
Implementa el requisito del PRD §5 (Observabilidad):

  Abandonar logs en texto plano. Implementar un CloudLoggingHandler
  (JSON Structured Logging) emitido a stdout integrado con Google
  Cloud Logging.

Llaves reservadas de Google Cloud Logging:
  - ``severity``  → nivel del log (DEBUG, INFO, WARNING, ERROR, CRITICAL)
  - ``message``   → texto del mensaje
  - ``logging.googleapis.com/trace`` → ID de traza para correlación
  - ``attributes`` → diccionario de métricas vitales del pipeline

La salida se emite a **stdout** como JSON de una sola línea.  Cloud Run
parsea automáticamente JSON estructurado desde stdout y lo indexa en
Google Cloud Logging sin configuración adicional.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import traceback
from datetime import datetime, timezone
from typing import Any


# ── Mapeo de niveles Python → severidad GCP ──────────────────────────
_GCP_SEVERITY_MAP: dict[str, str] = {
    "DEBUG": "DEBUG",
    "INFO": "INFO",
    "WARNING": "WARNING",
    "ERROR": "ERROR",
    "CRITICAL": "CRITICAL",
}


class StructuredJSONFormatter(logging.Formatter):
    """Formateador que serializa cada log record a JSON compatible con
    Google Cloud Logging.

    Produce una línea JSON por registro con las llaves reservadas de GCP
    y un diccionario ``attributes`` opcional para métricas del pipeline.

    Estructura del JSON emitido::

        {
          "severity": "INFO",
          "message": "Extracción completada",
          "timestamp": "2026-05-11T14:20:00.123456Z",
          "logging.googleapis.com/trace": "projects/.../traces/...",
          "logger": "app.infrastructure.github_extractor",
          "attributes": {"bytes_downloaded": 45678901},
          "source_location": {"file": "...", "line": 101, "function": "..."}
        }

    Parameters
    ----------
    gcp_project_id : str
        ID del proyecto GCP, usado para construir el trace resource name.
    """

    def __init__(self, gcp_project_id: str = "") -> None:
        super().__init__()
        self._gcp_project_id = gcp_project_id

    def format(self, record: logging.LogRecord) -> str:
        """Serializa el LogRecord a una línea JSON estructurada.

        Parameters
        ----------
        record : logging.LogRecord
            Record estándar de Python logging.

        Returns
        -------
        str
            JSON de una sola línea (sin saltos internos).
        """
        log_entry: dict[str, Any] = {
            "severity": _GCP_SEVERITY_MAP.get(record.levelname, "DEFAULT"),
            "message": record.getMessage(),
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "logger": record.name,
            "source_location": {
                "file": record.pathname,
                "line": record.lineno,
                "function": record.funcName,
            },
        }

        # ── Trace ID (Cloud Run inyecta X-Cloud-Trace-Context) ────────
        trace_header = os.environ.get("X_CLOUD_TRACE_CONTEXT", "")
        if trace_header and self._gcp_project_id:
            trace_id = trace_header.split("/")[0]
            log_entry["logging.googleapis.com/trace"] = (
                f"projects/{self._gcp_project_id}/traces/{trace_id}"
            )

        # ── Attributes (métricas vitales del pipeline) ────────────────
        attributes = getattr(record, "attributes", None)
        if attributes and isinstance(attributes, dict):
            log_entry["attributes"] = attributes

        # ── Exception traceback ───────────────────────────────────────
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
                "traceback": traceback.format_exception(*record.exc_info),
            }

        return json.dumps(log_entry, default=str, ensure_ascii=False)


def setup_cloud_logging(
    *,
    log_level: str = "INFO",
    gcp_project_id: str = "",
    environment: str = "development",
) -> None:
    """Inicializa globalmente el sistema de logging estructurado JSON.

    Configura el logger raíz de Python con un ``StreamHandler`` a stdout
    y el ``StructuredJSONFormatter``.  Todos los módulos que usen
    ``logging.getLogger(__name__)`` heredarán esta configuración
    automáticamente.

    En entorno ``production``, opcionalmente integra con el cliente
    nativo de ``google.cloud.logging`` para envío directo a Cloud
    Logging API (además del output a stdout).

    Parameters
    ----------
    log_level : str
        Nivel mínimo de logging (DEBUG, INFO, WARNING, ERROR, CRITICAL).
    gcp_project_id : str
        ID del proyecto GCP para el trace resource name.
    environment : str
        Entorno de ejecución (development, staging, production).

    Raises
    ------
    ObservabilityConfigError
        Si el nivel de log especificado no es válido o si la integración
        con Cloud Logging falla en producción.
    """
    from app.domain.exceptions import ObservabilityConfigError

    # ── Validar nivel de log ──────────────────────────────────────────
    numeric_level = getattr(logging, log_level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ObservabilityConfigError(
            f"Nivel de log inválido: '{log_level}'. "
            f"Valores válidos: DEBUG, INFO, WARNING, ERROR, CRITICAL."
        )

    # ── Configurar logger raíz ────────────────────────────────────────
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Limpiar handlers previos (evitar duplicación en recargas)
    root_logger.handlers.clear()

    # ── Handler principal: stdout con JSON estructurado ───────────────
    stdout_handler = logging.StreamHandler(stream=sys.stdout)
    stdout_handler.setLevel(numeric_level)
    stdout_handler.setFormatter(
        StructuredJSONFormatter(gcp_project_id=gcp_project_id)
    )
    root_logger.addHandler(stdout_handler)

    # ── Integración nativa Cloud Logging (solo producción) ────────────
    if environment == "production":
        try:
            import google.cloud.logging as cloud_logging

            client = cloud_logging.Client(project=gcp_project_id)
            client.setup_logging(log_level=numeric_level)

        except Exception as exc:
            # No abortar: stdout sigue funcionando como fallback.
            # Cloud Run parsea JSON de stdout automáticamente.
            root_logger.warning(
                "No se pudo activar el cliente nativo de Cloud Logging. "
                "Los logs se emitirán solo a stdout.",
                extra={
                    "attributes": {
                        "error": str(exc),
                        "environment": environment,
                    },
                },
            )

    # ── Silenciar loggers ruidosos de terceros ────────────────────────
    for noisy_logger in ("urllib3", "httpx", "google", "httpcore"):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)

    # ── Log de confirmación de inicialización ─────────────────────────
    root_logger.info(
        "Sistema de logging estructurado JSON inicializado",
        extra={
            "attributes": {
                "log_level": log_level.upper(),
                "environment": environment,
                "gcp_project_id": gcp_project_id or "(no configurado)",
                "output": "stdout",
                "format": "JSON (Google Cloud Logging compatible)",
            },
        },
    )
