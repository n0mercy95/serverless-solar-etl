"""
test_phase_3_1_cloud_logging.py — Tests para Google Cloud Logging
==================================================================
Verifica la funcionalidad del formateador JSON estructurado y la
correcta inicialización del handler de Cloud Logging requerido en
la Fase 3.1 del PRD.
"""

from __future__ import annotations

import json
import logging
from unittest.mock import patch

import pytest

from app.domain.exceptions import ObservabilityConfigError
from app.infrastructure.cloud_logging import (
    StructuredJSONFormatter,
    setup_cloud_logging,
)


def test_structured_json_formatter_basic(caplog):
    """Verifica que el formateador genera JSON válido con los campos esperados."""
    formatter = StructuredJSONFormatter(gcp_project_id="test-project")
    
    # Creamos un LogRecord de prueba
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname="fake_path.py",
        lineno=42,
        msg="Test message",
        args=(),
        exc_info=None,
    )
    
    # Añadimos atributos custom como hace el resto del código
    record.attributes = {"station_id": 5, "records": 100}
    
    output = formatter.format(record)
    
    # Validar que es JSON válido
    parsed = json.loads(output)
    
    # Validar campos de GCP requeridos
    assert parsed["severity"] == "INFO"
    assert parsed["message"] == "Test message"
    assert "timestamp" in parsed
    
    # Validar atributos
    assert "attributes" in parsed
    assert parsed["attributes"]["station_id"] == 5
    assert parsed["attributes"]["records"] == 100
    
    # Validar location
    assert parsed["source_location"]["file"] == "fake_path.py"
    assert parsed["source_location"]["line"] == 42


@patch.dict("os.environ", {"X_CLOUD_TRACE_CONTEXT": "105445aa7843bc8bf206b12000100000/1;o=1"})
def test_structured_json_formatter_trace():
    """Verifica que el formateador extrae el trace ID si está en el entorno."""
    formatter = StructuredJSONFormatter(gcp_project_id="test-project")
    
    record = logging.LogRecord(
        name="test", level=logging.DEBUG, pathname="", lineno=0, msg="test", args=(), exc_info=None
    )
    
    output = formatter.format(record)
    parsed = json.loads(output)
    
    # Debe contener la llave exacta requerida por GCP
    assert "logging.googleapis.com/trace" in parsed
    assert parsed["logging.googleapis.com/trace"] == "projects/test-project/traces/105445aa7843bc8bf206b12000100000"


def test_structured_json_formatter_exception():
    """Verifica que las excepciones se formatean correctamente dentro del JSON."""
    formatter = StructuredJSONFormatter()
    
    try:
        1 / 0
    except ZeroDivisionError:
        import sys
        exc_info = sys.exc_info()
        
    record = logging.LogRecord(
        name="test", level=logging.ERROR, pathname="", lineno=0, msg="Error", args=(), exc_info=exc_info
    )
    
    output = formatter.format(record)
    parsed = json.loads(output)
    
    assert "exception" in parsed
    assert parsed["exception"]["type"] == "ZeroDivisionError"
    assert "division by zero" in parsed["exception"]["message"]
    assert len(parsed["exception"]["traceback"]) > 0


def test_setup_cloud_logging_invalid_level():
    """Verifica que setup_cloud_logging rechaza niveles de log inválidos."""
    with pytest.raises(ObservabilityConfigError, match="Nivel de log inválido"):
        setup_cloud_logging(log_level="INVALID_LEVEL")


def test_setup_cloud_logging_development():
    """Verifica la configuración básica en desarrollo (solo stdout, sin cliente de GCP)."""
    # Limpiamos handlers previos por si acaso
    logging.getLogger().handlers.clear()
    
    setup_cloud_logging(log_level="DEBUG", environment="development")
    
    root_logger = logging.getLogger()
    assert root_logger.level == logging.DEBUG
    
    # Debe tener un handler configurado
    assert len(root_logger.handlers) == 1
    handler = root_logger.handlers[0]
    
    # Debe ser StreamHandler y usar StructuredJSONFormatter
    assert isinstance(handler, logging.StreamHandler)
    assert isinstance(handler.formatter, StructuredJSONFormatter)
