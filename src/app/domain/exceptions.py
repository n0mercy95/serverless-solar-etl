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
