"""
domain/exceptions.py — Jerarquía de Excepciones del ETL Solar
=============================================================
El PRD exige evitar cláusulas amplias ``except Exception as e``.
Cada nivel hereda de ``SolarETLError`` para habilitar captura granular
sin perder la posibilidad de atrapar *todas* las fallas del pipeline
con un solo tipo base.
"""

from __future__ import annotations


class SolarETLError(Exception):
    """Excepción base del pipeline ETL Solar.

    Todas las excepciones específicas del dominio deben heredar de esta
    clase para garantizar una jerarquía controlada de errores.
    """


class DataExtractionError(SolarETLError):
    """Fallo genérico durante la extracción de datos desde cualquier fuente."""


class DataSourceUnavailableError(DataExtractionError):
    """La fuente de datos (GitHub Raw, ScienceDB, etc.) no respondió
    o retornó un status HTTP inesperado."""


class DataValidationError(SolarETLError):
    """Los datos extraídos no cumplen las validaciones de integridad
    (buffer vacío, CSV corrupto, conteo de registros incorrecto)."""


# ── Excepciones de Transformación (Fase 2) ────────────────────────────

class DataTransformationError(SolarETLError):
    """Fallo genérico durante la fase de transformación de datos.

    Todas las excepciones específicas de transformación deben heredar
    de esta clase para permitir captura granular en el pipeline.
    """


class TemporalAlignmentError(DataTransformationError):
    """Las marcas de tiempo no cumplen la grilla estricta de 15 minutos.

    Se lanza cuando se detectan:
    - Timestamps duplicados para una misma estación.
    - Gaps temporales (intervalos > 15 min) en la serie de una estación.
    - Timestamps que no se alinean a múltiplos exactos de 15 minutos.
    """


class IrradianceOutOfBoundsError(DataTransformationError):
    """La irradiancia global excede la constante solar extraterrestre
    o es negativa.

    Restricción física del PRD §4: abortar ejecución inmediatamente
    si fallan las validaciones físicas, en lugar de aplicar políticas
    de reintento.
    """
