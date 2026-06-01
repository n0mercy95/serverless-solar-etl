"""
test_schema_profiler.py — Pruebas Unitarias para el SchemaProfiler
==================================================================
Valida el comportamiento y formato del reporte estructural ASCII generado por
el SchemaProfiler, así como sus cálculos de score estructural.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import polars as pl
import pytest

# Resolver imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from app.application.schema_profiler import SchemaProfiler


@pytest.fixture
def base_schema_data() -> pl.DataFrame:
    """Genera un DataFrame mock con todos los tipos esperados correctos."""
    return pl.DataFrame({
        "date_time": [datetime(2023, 6, 21, 12, 0)],
        "station_id": [1],
        "nwp_globalirrad": [100.0],
        "nwp_directirrad": [70.0],
        "nwp_temperature": [25.0],
        "nwp_humidity": [50.0],
        "nwp_windspeed": [5.0],
        "nwp_winddirection": [180.0],
        "nwp_pressure": [1013.0],
        "lmd_totalirrad": [95.0],
        "lmd_diffuseirrad": [30.0],
        "lmd_temperature": [25.5],
        "lmd_pressure": [1013.3],
        "lmd_winddirection": [185.0],
        "lmd_windspeed": [5.2],
        "power": [1.5],
    })


def test_schema_profiler_ok_types(base_schema_data):
    """Verifica que si todos los tipos son correctos y coinciden, el score es 100%."""
    profiler = SchemaProfiler(base_schema_data)
    report = profiler.generate_report("Raw Intake")

    assert isinstance(report, str)
    assert "PVOD ETL: DATA INTAKE & SCHEMA REPORT" in report
    assert "Phase:              Raw Intake" in report
    assert "Schema Integrity Score: 100%" in report
    assert "[OK]" in report
    assert "[WARN]" not in report
    assert "[ERROR]" not in report


def test_schema_profiler_warns_on_raw_csv_string_datetime(base_schema_data):
    """Verifica el comportamiento realista del intake: date_time es String.
    
    Debe marcar [WARN] -> Cast needed para timestamp/date_time, pero mantener
    el Score en 100% de presencia/integridad de columnas.
    """
    raw_csv_data = base_schema_data.with_columns(
        pl.col("date_time").cast(pl.String)
    )
    profiler = SchemaProfiler(raw_csv_data)
    report = profiler.generate_report("Raw Intake")

    assert "[WARN] -> Cast needed" in report
    assert "Schema Integrity Score: 100%" in report


def test_schema_profiler_handles_missing_column(base_schema_data):
    """Verifica que si falta una columna esperada, marque [ERROR] y baje el score."""
    incomplete_data = base_schema_data.drop("power")
    profiler = SchemaProfiler(incomplete_data)
    report = profiler.generate_report("Raw Intake")

    assert "[ERROR] -> Missing" in report
    # 15 de 16 columnas esperadas están presentes = 93.75% -> 94%
    assert "Schema Integrity Score: 94%" in report


def test_schema_profiler_handles_extra_column(base_schema_data):
    """Verifica que las columnas adicionales/no esperadas se muestren y no bajen el score."""
    extra_data = base_schema_data.with_columns(
        pl.lit("mock_val").alias("extra_field")
    )
    profiler = SchemaProfiler(extra_data)
    report = profiler.generate_report("Raw Intake")

    assert "extra_field" in report
    assert "N/A" in report  # Expected type de la columna extra es N/A
    assert "Schema Integrity Score: 100%" in report


def test_schema_profiler_handles_empty_dataframe(base_schema_data):
    """Verifica el comportamiento ante un DataFrame vacío pero con esquema correcto."""
    empty_df = base_schema_data.clear()
    profiler = SchemaProfiler(empty_df)
    report = profiler.generate_report("Empty Phase")

    assert "Total Records:              0" in report
    assert "Schema Integrity Score: 100%" in report
